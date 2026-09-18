import hashlib
import hmac
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .ai.pipeline import AIPipelineUnavailable, extract_structured, resolve_zone_asset
from .config_loader import get_house_config
from .db import get_db
from .domain import (
    audit,
    create_action,
    find_duplicate,
    recurrence_count,
    transition_initiative,
    transition_issue,
    transition_work_order,
)
from .enums import InitiativeState, IssueState, WorkOrderState
from .integrations.max_adapter import MaxAdapterError, build_max_adapter
from .models import (
    Asset,
    AuditEvent,
    Evidence,
    House,
    Initiative,
    Issue,
    PollVote,
    Signal,
    Submission,
    WebhookEvent,
    WorkOrder,
    Zone,
    Verification,
)
from .schemas import (
    AcceptRequest,
    ConfirmRequest,
    DuplicateResolutionRequest,
    EvidenceCreate,
    HandoffRequest,
    InitiativeCreate,
    ManualResolveRequest,
    PollRequest,
    SignalCreate,
    SubmitRequest,
    VerifyRequest,
    WorkOrderCreate,
    WorkOrderPatch,
)
from .serializers import asset_dict, audit_dict, house_dict, initiative_dict, issue_dict, signal_dict, work_order_dict, zone_dict
from .settings import get_settings
from .state_machine import InvalidTransition


settings = get_settings()
max_adapter = build_max_adapter(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="ДомПульс API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def not_found(kind: str, object_id: str):
    raise HTTPException(status_code=404, detail=f"{kind} {object_id} not found")


def get_issue(db: Session, issue_id: str) -> Issue:
    return db.get(Issue, issue_id) or not_found("Issue", issue_id)


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate or conflicting operation") from exc


def run_issue_transition(db: Session, issue: Issue, target: IssueState, actor: str):
    try:
        transition_issue(db, issue, target, actor)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok", "max_mode": max_adapter.mode, "llm_mode": settings.llm_mode}


@app.get("/integrations/max/status")
async def max_status():
    try:
        bot = await max_adapter.get_bot()
        return {"mode": max_adapter.mode, "connected": True, "bot": bot}
    except MaxAdapterError as exc:
        return {"mode": max_adapter.mode, "connected": False, "error": str(exc)}


@app.get("/integrations/max/chats/{chat_id}/permissions")
async def max_permissions(chat_id: str):
    try:
        return await max_adapter.check_chat_permissions(chat_id)
    except MaxAdapterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/houses")
def list_houses(db: Session = Depends(get_db)):
    return [house_dict(item) for item in db.scalars(select(House).order_by(House.id)).all()]


@app.get("/houses/{house_id}")
def read_house(house_id: str, db: Session = Depends(get_db)):
    house = db.get(House, house_id) or not_found("House", house_id)
    return house_dict(house)


def operational_state(db: Session, asset: Asset) -> str:
    issues = db.scalars(select(Issue).where(Issue.asset_id == asset.id)).all()
    states = {IssueState(item.state) for item in issues}
    if IssueState.WORK_IN_PROGRESS in states:
        return "WORK_IN_PROGRESS"
    if IssueState.DONE_PENDING_VERIFICATION in states:
        return "VERIFICATION"
    if any(item.recurrence_count >= get_house_config(asset.house_id).recurrence.count and item.state != IssueState.CLOSED.value for item in issues):
        return "RECURRING"
    if any(state not in {IssueState.CLOSED, IssueState.CANCELLED, IssueState.REJECTED, IssueState.DUPLICATE} for state in states):
        return "ACTIVE_ISSUE"
    return "HEALTHY" if issues else "UNKNOWN"


@app.get("/houses/{house_id}/assets")
def list_assets(house_id: str, db: Session = Depends(get_db)):
    if not db.get(House, house_id):
        not_found("House", house_id)
    return [asset_dict(item, operational_state(db, item)) for item in db.scalars(select(Asset).where(Asset.house_id == house_id)).all()]


@app.get("/houses/{house_id}/state")
def house_state(house_id: str, db: Session = Depends(get_db)):
    house = db.get(House, house_id) or not_found("House", house_id)
    active_states = [state.value for state in IssueState if state not in {IssueState.CLOSED, IssueState.CANCELLED, IssueState.REJECTED, IssueState.DUPLICATE}]
    issues = db.scalars(select(Issue).where(Issue.house_id == house_id)).all()
    assets = db.scalars(select(Asset).where(Asset.house_id == house_id)).all()
    initiatives = db.scalars(select(Initiative).where(Initiative.house_id == house_id, Initiative.state != InitiativeState.CLOSED.value)).all()
    threshold = get_house_config(house_id).recurrence.count
    return {
        "house": house_dict(house),
        "metrics": {
            "active_issues": sum(item.state in active_states for item in issues),
            "work_in_progress": sum(item.state == IssueState.WORK_IN_PROGRESS.value for item in issues),
            "recurring_issues": sum(item.recurrence_count >= threshold for item in issues if item.state in active_states),
            "initiatives": len(initiatives),
        },
        "assets": [asset_dict(item, operational_state(db, item)) for item in assets],
        "issues": [issue_dict(item) for item in sorted(issues, key=lambda item: item.last_seen_at, reverse=True)[:20]],
        "initiatives": [initiative_dict(item) for item in initiatives],
        "integration": {"max": max_adapter.mode, "external_submission": "SIMULATED"},
    }


def process_signal(db: Session, payload: SignalCreate) -> dict[str, Any]:
    if not db.get(House, payload.house_id):
        not_found("House", payload.house_id)
    if payload.external_id:
        existing = db.scalar(select(Signal).where(Signal.source_type == payload.source_type, Signal.external_id == payload.external_id))
        if existing:
            linked_issue = db.scalar(select(Issue).join(Issue.signals).where(Signal.id == existing.id))
            return {"signal": signal_dict(existing), "issue": issue_dict(linked_issue) if linked_issue else None, "idempotent_replay": True}
    signal = Signal(**payload.model_dump(exclude={"manual_category", "manual_zone_id", "force_ai_failure"}))
    db.add(signal)
    try:
        extraction = extract_structured(payload.text, force_failure=payload.force_ai_failure)
    except AIPipelineUnavailable:
        signal.ai_actionability_score = None
        commit(db)
        return {
            "signal": signal_dict(signal),
            "fallback": {"type": "MANUAL_CLASSIFICATION", "message": "Не удалось автоматически разобрать сообщение. Выберите категорию и место."},
        }
    signal.ai_actionability_score = extraction.confidence
    if not extraction.actionable or extraction.intent == "noise":
        commit(db)
        return {"signal": signal_dict(signal), "classification": extraction.model_dump(), "result": "NO_ACTION"}
    resolution = resolve_zone_asset(db, payload.house_id, extraction)
    if extraction.intent == "confirmation":
        candidate, score = find_duplicate(
            db,
            house_id=payload.house_id,
            zone_id=resolution.zone.id if resolution.zone else None,
            asset_id=resolution.asset.id if resolution.asset else None,
            category=extraction.category,
            text=payload.text,
        )
        if candidate and score >= 0.65:
            candidate.signals.append(signal)
            candidate.confirmations_count += 1
            candidate.last_seen_at = datetime.now(timezone.utc)
            audit(db, "Issue", candidate.id, "SIGNAL_CLUSTERED", payload.author_id, details={"score": score})
            commit(db)
            return {"signal": signal_dict(signal), "classification": extraction.model_dump(), "issue": issue_dict(candidate), "clustered": True}
        candidate = db.scalar(
            select(Issue)
            .where(
                Issue.house_id == payload.house_id,
                Issue.state.in_([IssueState.NEEDS_CONFIRMATION.value, IssueState.CONFIRMED.value, IssueState.ACTION_READY.value]),
            )
            .order_by(Issue.last_seen_at.desc())
        )
        if candidate:
            candidate.signals.append(signal)
            candidate.confirmations_count += 1
            candidate.last_seen_at = datetime.now(timezone.utc)
            audit(db, "Issue", candidate.id, "CONFIRMATION_CLUSTERED", payload.author_id, details={"rule": "latest_active_issue"})
            commit(db)
            return {"signal": signal_dict(signal), "classification": extraction.model_dump(), "issue": issue_dict(candidate), "clustered": True}
    if extraction.intent == "initiative":
        initiative = Initiative(
            house_id=payload.house_id,
            zone_id=resolution.zone.id if resolution.zone else None,
            related_asset_id=resolution.asset.id if resolution.asset else None,
            title="Инициатива жителей: дополнительное освещение" if extraction.category == "lighting" else "Инициатива жителей",
            summary=payload.text,
            options=["Поддерживаю", "Нужно обсудить расположение", "Не поддерживаю"],
            votes={},
            requires_formal_process=True,
        )
        db.add(initiative)
        db.flush()
        transition_initiative(db, initiative, InitiativeState.DRAFT, "ai-pipeline")
        transition_initiative(db, initiative, InitiativeState.DISCUSSION, "ai-pipeline")
        transition_initiative(db, initiative, InitiativeState.INFORMAL_POLL, payload.author_id)
        initiative.informal_poll_state = "OPEN"
        commit(db)
        return {"signal": signal_dict(signal), "classification": extraction.model_dump(), "initiative": initiative_dict(initiative)}
    if resolution.needs_clarification and not payload.manual_zone_id:
        commit(db)
        return {
            "signal": signal_dict(signal),
            "classification": extraction.model_dump(),
            "fallback": {"type": "ZONE_CLARIFICATION", "message": "Уточните место проблемы", "choices": [zone_dict(item) for item in db.scalars(select(Zone).where(Zone.house_id == payload.house_id)).all()]},
        }
    zone_id = payload.manual_zone_id or (resolution.zone.id if resolution.zone else None)
    asset_id = resolution.asset.id if resolution.asset else None
    candidate, score = find_duplicate(db, house_id=payload.house_id, zone_id=zone_id, asset_id=asset_id, category=extraction.category, text=payload.text)
    if candidate and score >= 0.78:
        candidate.signals.append(signal)
        candidate.confirmations_count += 1
        candidate.last_seen_at = datetime.now(timezone.utc)
        audit(db, "Issue", candidate.id, "SIGNAL_CLUSTERED", payload.author_id, details={"score": score})
        commit(db)
        return {"signal": signal_dict(signal), "classification": extraction.model_dump(), "issue": issue_dict(candidate), "clustered": True, "duplicate_score": score}
    if candidate and score >= 0.55:
        commit(db)
        return {
            "signal": signal_dict(signal),
            "classification": extraction.model_dump(),
            "fallback": {"type": "DUPLICATE_CONFIRMATION", "candidate": issue_dict(candidate), "score": score, "actions": ["LINK", "CREATE_NEW"]},
        }
    category = payload.manual_category or extraction.category
    count = recurrence_count(db, payload.house_id, asset_id, category)
    title = (resolution.asset.name if resolution.asset else category.capitalize()) + ": проблема"
    issue = Issue(
        house_id=payload.house_id,
        zone_id=zone_id,
        asset_id=asset_id,
        category=category,
        symptom=extraction.symptom,
        title=title,
        description=payload.text,
        severity="high" if extraction.recurrence_hint or count > 1 else "medium",
        recurrence_count=count,
        signals=[signal],
    )
    db.add(issue)
    db.flush()
    transition_issue(db, issue, IssueState.NEEDS_CONFIRMATION, "ai-pipeline")
    commit(db)
    return {"signal": signal_dict(signal), "classification": extraction.model_dump(), "issue": issue_dict(issue), "asset_confidence": resolution.confidence}


@app.post("/signals", status_code=201)
def create_signal(payload: SignalCreate, db: Session = Depends(get_db)):
    return process_signal(db, payload)


@app.get("/signals/{signal_id}")
def read_signal(signal_id: str, db: Session = Depends(get_db)):
    signal = db.get(Signal, signal_id) or not_found("Signal", signal_id)
    return signal_dict(signal)


@app.post("/signals/{signal_id}/resolve-duplicate")
def resolve_duplicate(signal_id: str, payload: DuplicateResolutionRequest, db: Session = Depends(get_db)):
    signal = db.get(Signal, signal_id) or not_found("Signal", signal_id)
    candidate = get_issue(db, payload.candidate_issue_id)
    if candidate.house_id != signal.house_id:
        raise HTTPException(status_code=409, detail="Signal and candidate belong to different houses")
    already_linked = any(item.id == signal.id for item in candidate.signals)
    if payload.decision == "LINK":
        if not already_linked:
            candidate.signals.append(signal)
            candidate.confirmations_count += 1
            candidate.last_seen_at = datetime.now(timezone.utc)
            audit(db, "Issue", candidate.id, "DUPLICATE_LINKED", payload.actor_id, details={"signal_id": signal.id})
        commit(db)
        return issue_dict(candidate, detailed=True)
    if already_linked:
        raise HTTPException(status_code=409, detail="Signal is already linked")
    issue = Issue(
        house_id=signal.house_id,
        zone_id=candidate.zone_id,
        asset_id=candidate.asset_id,
        category=candidate.category,
        symptom=candidate.symptom,
        title=f"{candidate.title} — отдельная проблема",
        description=signal.text,
        severity=candidate.severity,
        recurrence_count=recurrence_count(db, signal.house_id, candidate.asset_id, candidate.category),
        signals=[signal],
    )
    db.add(issue)
    db.flush()
    transition_issue(db, issue, IssueState.NEEDS_CONFIRMATION, payload.actor_id)
    audit(db, "Issue", issue.id, "DUPLICATE_REJECTED_NEW_ISSUE", payload.actor_id, details={"candidate_issue_id": candidate.id})
    commit(db)
    return issue_dict(issue, detailed=True)


@app.get("/issues")
def list_issues(house_id: str | None = None, db: Session = Depends(get_db)):
    query = select(Issue).order_by(Issue.last_seen_at.desc())
    if house_id:
        query = query.where(Issue.house_id == house_id)
    return [issue_dict(item) for item in db.scalars(query).all()]


@app.get("/issues/{issue_id}")
def read_issue(issue_id: str, db: Session = Depends(get_db)):
    return issue_dict(get_issue(db, issue_id), detailed=True)


@app.post("/issues/{issue_id}/confirm")
def confirm_issue(issue_id: str, payload: ConfirmRequest, db: Session = Depends(get_db)):
    issue = get_issue(db, issue_id)
    run_issue_transition(db, issue, IssueState.CONFIRMED, payload.actor_id)
    issue.confirmations_count += 1
    create_action(db, issue)
    run_issue_transition(db, issue, IssueState.ACTION_READY, "domain")
    commit(db)
    return issue_dict(issue, detailed=True)


@app.post("/issues/{issue_id}/submit")
def submit_issue(issue_id: str, payload: SubmitRequest, db: Session = Depends(get_db)):
    issue = get_issue(db, issue_id)
    if not issue.actions:
        raise HTTPException(status_code=409, detail="Issue has no confirmed action")
    action = issue.actions[-1]
    config = get_house_config(issue.house_id)
    route = config.routing.get(issue.category) or config.routing["default"]
    submission = Submission(
        issue=issue,
        action_id=action.id,
        destination_type=route.destination_type,
        destination_id=route.destination,
        channel="demo_uk_portal",
        is_simulated=True,
    )
    db.add(submission)
    run_issue_transition(db, issue, IssueState.SUBMITTED, payload.actor_id)
    commit(db)
    return issue_dict(issue, detailed=True)


@app.post("/issues/{issue_id}/accept")
def accept_issue(issue_id: str, payload: AcceptRequest, db: Session = Depends(get_db)):
    issue = get_issue(db, issue_id)
    run_issue_transition(db, issue, IssueState.ACCEPTED, payload.actor_id)
    commit(db)
    return issue_dict(issue, detailed=True)


@app.post("/issues/{issue_id}/verify")
def verify_issue(issue_id: str, payload: VerifyRequest, db: Session = Depends(get_db)):
    issue = get_issue(db, issue_id)
    verification = Verification(issue=issue, **payload.model_dump())
    db.add(verification)
    if payload.result == "confirmed":
        run_issue_transition(db, issue, IssueState.VERIFIED, payload.verifier_id)
        run_issue_transition(db, issue, IssueState.CLOSED, "domain")
        if issue.work_orders and issue.work_orders[-1].status == WorkOrderState.DONE.value:
            transition_work_order(db, issue.work_orders[-1], WorkOrderState.ACCEPTED, payload.verifier_id)
    else:
        run_issue_transition(db, issue, IssueState.REOPENED, payload.verifier_id)
        if issue.work_orders and issue.work_orders[-1].status == WorkOrderState.DONE.value:
            transition_work_order(db, issue.work_orders[-1], WorkOrderState.REWORK_REQUIRED, payload.verifier_id)
    commit(db)
    return issue_dict(issue, detailed=True)


@app.get("/assets/{asset_id}")
def read_asset(asset_id: str, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id) or not_found("Asset", asset_id)
    return asset_dict(asset, operational_state(db, asset))


@app.get("/assets/{asset_id}/timeline")
def asset_timeline(asset_id: str, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id) or not_found("Asset", asset_id)
    issues = db.scalars(select(Issue).where(Issue.asset_id == asset_id).order_by(Issue.first_seen_at.desc())).all()
    events = []
    for issue in issues:
        events.append({"type": "issue", **issue_dict(issue)})
        for order in issue.work_orders:
            events.append({"type": "work_order", **work_order_dict(order)})
    return {"asset": asset_dict(asset, operational_state(db, asset)), "events": events}


@app.post("/work-orders", status_code=201)
def create_work_order(payload: WorkOrderCreate, db: Session = Depends(get_db)):
    issue = get_issue(db, payload.issue_id)
    if issue.state != IssueState.ACCEPTED.value:
        raise HTTPException(status_code=409, detail="Issue must be ACCEPTED before a work order is created")
    order = WorkOrder(
        issue=issue,
        asset_id=issue.asset_id,
        assignee_id=payload.assignee_id,
        title=payload.title or issue.title,
        instructions=payload.instructions,
        priority=payload.priority,
    )
    db.add(order)
    db.flush()
    transition_work_order(db, order, WorkOrderState.ASSIGNED, "uk-demo")
    commit(db)
    return work_order_dict(order)


@app.patch("/work-orders/{order_id}")
def patch_work_order(order_id: str, payload: WorkOrderPatch, db: Session = Depends(get_db)):
    order = db.get(WorkOrder, order_id) or not_found("WorkOrder", order_id)
    try:
        transition_work_order(db, order, WorkOrderState(payload.status), payload.actor_id)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    commit(db)
    return work_order_dict(order)


@app.post("/work-orders/{order_id}/evidence", status_code=201)
def add_evidence(order_id: str, payload: EvidenceCreate, db: Session = Depends(get_db)):
    order = db.get(WorkOrder, order_id) or not_found("WorkOrder", order_id)
    if order.status not in {WorkOrderState.IN_PROGRESS.value, WorkOrderState.DONE.value}:
        raise HTTPException(status_code=409, detail="Evidence can only be added during or after work")
    evidence = Evidence(work_order=order, **payload.model_dump())
    db.add(evidence)
    audit(db, "WorkOrder", order.id, "EVIDENCE_ADDED", payload.author_id, details={"type": payload.type})
    commit(db)
    return work_order_dict(order)


@app.post("/initiatives", status_code=201)
def create_initiative(payload: InitiativeCreate, db: Session = Depends(get_db)):
    if not db.get(House, payload.house_id):
        not_found("House", payload.house_id)
    initiative = Initiative(**payload.model_dump(), votes={})
    db.add(initiative)
    db.flush()
    transition_initiative(db, initiative, InitiativeState.DRAFT, "representative-demo")
    transition_initiative(db, initiative, InitiativeState.DISCUSSION, "representative-demo")
    transition_initiative(db, initiative, InitiativeState.INFORMAL_POLL, "representative-demo")
    initiative.informal_poll_state = "OPEN"
    commit(db)
    return initiative_dict(initiative)


@app.get("/initiatives/{initiative_id}")
def read_initiative(initiative_id: str, db: Session = Depends(get_db)):
    initiative = db.get(Initiative, initiative_id) or not_found("Initiative", initiative_id)
    return initiative_dict(initiative)


@app.post("/initiatives/{initiative_id}/poll")
def vote(initiative_id: str, payload: PollRequest, db: Session = Depends(get_db)):
    initiative = db.get(Initiative, initiative_id) or not_found("Initiative", initiative_id)
    if initiative.state != InitiativeState.INFORMAL_POLL.value:
        raise HTTPException(status_code=409, detail="Poll is not open")
    if payload.option not in initiative.options:
        raise HTTPException(status_code=422, detail="Unknown poll option")
    db.add(PollVote(initiative_id=initiative.id, **payload.model_dump()))
    votes = dict(initiative.votes)
    votes[payload.option] = votes.get(payload.option, 0) + 1
    initiative.votes = votes
    commit(db)
    return initiative_dict(initiative)


@app.post("/initiatives/{initiative_id}/handoff")
def handoff(initiative_id: str, payload: HandoffRequest, db: Session = Depends(get_db)):
    initiative = db.get(Initiative, initiative_id) or not_found("Initiative", initiative_id)
    if initiative.state == InitiativeState.INFORMAL_POLL.value:
        transition_initiative(db, initiative, InitiativeState.RESULT, payload.actor_id)
        initiative.informal_poll_state = "CLOSED"
    target = InitiativeState.FORMAL_HANDOFF_REQUIRED if initiative.requires_formal_process else InitiativeState.CLOSED
    transition_initiative(db, initiative, target, payload.actor_id)
    initiative.formal_handoff_type = payload.handoff_type if initiative.requires_formal_process else None
    commit(db)
    return initiative_dict(initiative)


@app.get("/audit/{entity_type}/{entity_id}")
def read_audit(entity_type: str, entity_id: str, db: Session = Depends(get_db)):
    events = db.scalars(
        select(AuditEvent).where(AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id).order_by(AuditEvent.created_at)
    ).all()
    return [audit_dict(item) for item in events]


def parse_max_update(payload: dict[str, Any]) -> SignalCreate | None:
    if payload.get("update_type") != "message_created":
        return None
    message = payload.get("message") or {}
    body = message.get("body") or {}
    sender = message.get("sender") or {}
    recipient = message.get("recipient") or {}
    text = body.get("text")
    house_id = payload.get("house_id") or "demo-house-a"
    if not text:
        return None
    return SignalCreate(
        house_id=house_id,
        text=text,
        author_id=str(sender.get("user_id", "max-user")),
        chat_id=str(recipient.get("chat_id") or payload.get("chat_id") or ""),
        source_type="max_message",
        external_id=str(body.get("mid") or message.get("id") or f"{payload.get('timestamp')}:{sender.get('user_id')}"),
        attachments=body.get("attachments") or [],
    )


@app.post("/integrations/max/webhook")
def max_webhook(
    payload: dict[str, Any],
    x_max_bot_api_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if settings.max_webhook_secret and not hmac.compare_digest(x_max_bot_api_secret or "", settings.max_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid MAX webhook secret")
    raw = repr(sorted(payload.items())).encode()
    event_id = str(payload.get("event_id") or payload.get("timestamp") or hashlib.sha256(raw).hexdigest())
    if db.get(WebhookEvent, event_id):
        return {"ok": True, "idempotent_replay": True}
    event = WebhookEvent(id=event_id, payload_hash=hashlib.sha256(raw).hexdigest())
    db.add(event)
    signal_payload = parse_max_update(payload)
    result = process_signal(db, signal_payload) if signal_payload else {"ignored": True}
    commit(db)
    return {"ok": True, "result": result}


@app.exception_handler(InvalidTransition)
async def invalid_transition_handler(_: Request, exc: InvalidTransition):
    return __import__("fastapi").responses.JSONResponse(status_code=409, content={"detail": str(exc)})
