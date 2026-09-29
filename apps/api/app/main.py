import hashlib
import hmac
import json
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

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
from .integrations.max_init_data import MaxInitDataError, validate_max_init_data
from .integrations.max_updates import parse_incoming_message, polling_is_active
from .models import (
    Asset,
    AuditEvent,
    Evidence,
    House,
    Initiative,
    Issue,
    IssueComment,
    IssueSignal,
    MaxProfile,
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
    AssistantChatRequest,
    BotHouseSelectionRequest,
    ConfirmRequest,
    DuplicateResolutionRequest,
    EvidenceCreate,
    HandoffRequest,
    HouseCreate,
    IssueCommentCreate,
    InitiativeCreate,
    ManualResolveRequest,
    MaxInitDataRequest,
    MaxHouseSelectionRequest,
    PollRequest,
    ResidentConfirmRequest,
    RouteSelectionRequest,
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
assistant_calls: dict[str, list[float]] = {}


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


def max_identity(init_data: str) -> tuple[str, str]:
    if not settings.max_bot_token:
        raise HTTPException(status_code=503, detail="MAX is not configured")
    try:
        validated = validate_max_init_data(
            init_data, settings.max_bot_token, max_age_seconds=settings.max_init_data_max_age_seconds
        )
        user_id = str(validated["user"]["id"])
    except (MaxInitDataError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Не удалось проверить вход через MAX") from exc
    return user_id, settings.role_for_max_user(user_id)


def require_internal_bot(request: Request) -> None:
    supplied = request.headers.get("x-dompuls-internal-key", "")
    if not settings.internal_api_key or not hmac.compare_digest(supplied, settings.internal_api_key):
        raise HTTPException(status_code=401, detail="Требуется внутренний ключ бота")


def authorize(
    request: Request,
    db: Session,
    *,
    house_id: str | None = None,
    roles: tuple[str, ...] = ("resident", "representative", "uk", "executor"),
    owner_id: str | None = None,
) -> str | None:
    """Authorize a public mutation; internal bot calls use a separate server key."""
    if settings.auth_mode == "demo":
        return None
    internal_key = request.headers.get("x-dompuls-internal-key", "")
    if settings.internal_api_key and hmac.compare_digest(internal_key, settings.internal_api_key):
        return None
    init_data = request.headers.get("x-max-init-data", "")
    if not init_data:
        raise HTTPException(status_code=401, detail="Откройте приложение из MAX, чтобы выполнить действие")
    user_id, role = max_identity(init_data)
    if role not in roles:
        raise HTTPException(status_code=403, detail="Это действие недоступно вашей роли")
    if owner_id and owner_id != user_id:
        raise HTTPException(status_code=403, detail="Можно изменить только своё обращение")
    if house_id:
        profile = db.get(MaxProfile, user_id)
        if not profile or profile.selected_house_id != house_id:
            raise HTTPException(status_code=403, detail="Сначала выберите этот дом в приложении")
    return user_id


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok", "max_mode": max_adapter.mode, "llm_mode": settings.llm_mode}


def local_assistant_answer(text: str, db: Session, house_id: str | None) -> str:
    lowered = text.lower()
    if "статус" in lowered or "что с домом" in lowered:
        if house_id and db.get(House, house_id):
            active = db.scalar(select(func.count()).select_from(Issue).where(Issue.house_id == house_id, Issue.state.in_(ACTIVE_ISSUE_STATES))) or 0
            return f"Сейчас открытых проблем по этому дому: {active}. Подробности есть в разделе «Дом», ваши обращения — в «Задачах»."
        return "Сначала выберите дом на карте или в списке — тогда покажу его состояние."
    if "ук" in lowered or "передать" in lowered:
        return "Житель сообщает и подтверждает проблему. Домоуправляющий проверяет её и выбирает маршрут, затем УК принимает работу. Пока передача в УК демонстрационная, официальный канал не подключён."
    if "домоуправ" in lowered or "роль" in lowered:
        return "Домоуправляющий проверяет подтверждения жителей и решает, какое обращение передать. В MAX роль назначается организатором; самостоятельно получить доступ УК или исполнителя нельзя."
    if "жалоб" in lowered or "проблем" in lowered or "обращен" in lowered:
        return "Напишите боту в MAX, что произошло и где, или нажмите «Сообщить о проблеме» в приложении. Если место понятно из текста, лишних вопросов не будет. Статус появится в «Задачах»."
    return "Я помогу сообщить о проблеме, найти статус обращения и разобраться с ролями. Спросите, например: «Как сообщить о поломке?» или «Что с моим домом?». Официальные сроки и контакты лучше уточнить в УК."


@app.get("/assistant/status")
def assistant_status():
    return {"mode": "OPENROUTER" if settings.llm_mode == "openrouter" and settings.llm_api_key else "LOCAL_RULES", "available": True}


@app.post("/assistant/chat")
async def assistant_chat(payload: AssistantChatRequest, request: Request, db: Session = Depends(get_db)):
    last = payload.messages[-1]
    if last.role != "user":
        raise HTTPException(status_code=422, detail="Последнее сообщение должно быть от пользователя")
    house_id = payload.house_id if payload.house_id and db.get(House, payload.house_id) else None
    # House status is answered from the database; never let an LLM invent it.
    if "статус" in last.content.lower() or "что с домом" in last.content.lower():
        return {"answer": local_assistant_answer(last.content, db, house_id), "mode": "LOCAL_RULES"}
    if settings.llm_mode == "openrouter" and settings.llm_api_key:
        init_data = request.headers.get("x-max-init-data", "")
        # Public website visitors receive local guidance; only an explicitly
        # launched MAX session may consume the external assistant quota.
        if not init_data:
            return {"answer": local_assistant_answer(last.content, db, house_id), "mode": "LOCAL_RULES"}
        user_id, _ = max_identity(init_data)
        now_tick = time.monotonic()
        recent = [tick for tick in assistant_calls.get(user_id, []) if now_tick - tick < 60]
        if len(recent) >= 10:
            raise HTTPException(status_code=429, detail="Слишком много сообщений. Попробуйте через минуту.")
        assistant_calls[user_id] = [*recent, now_tick]
        # Only the latest message explicitly written in the assistant chat is
        # sent upstream. Neither issue/group data nor earlier conversation or
        # generated replies are included, even if a client supplies them.
        content = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[электронная почта скрыта]", last.content)
        content = re.sub(r"(?<!\d)(?:\+7|8)[\s()\-]*\d[\d\s()\-]{8,15}(?!\d)", "[телефон скрыт]", content)
        safe_messages = [{"role": "user", "content": content}]
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.post(
                    settings.llm_api_url,
                    headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json", "HTTP-Referer": settings.max_miniapp_url, "X-Title": "DomPuls"},
                    json={"model": settings.llm_model, "messages": [
                        {"role": "system", "content": "Ты Макс, доброжелательный помощник ДомПульса. Отвечай по-русски, коротко и ясно. Не выдумывай факты о конкретном доме, сроках, законах и УК. Роли: житель сообщает, домоуправляющий передаёт, УК принимает и назначает, исполнитель выполняет, житель проверяет. Внешняя передача в УК пока демонстрационная. Не запрашивай персональные данные."},
                        *safe_messages,
                    ], "max_tokens": 300, "temperature": 0.3},
                )
                response.raise_for_status()
                answer = response.json()["choices"][0]["message"]["content"]
                if isinstance(answer, str) and answer.strip():
                    return {"answer": answer.strip()[:2000], "mode": "OPENROUTER"}
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            pass
    return {"answer": local_assistant_answer(last.content, db, house_id), "mode": "LOCAL_RULES"}


@app.get("/integrations/max/status")
async def max_status():
    try:
        bot = await max_adapter.get_bot()
        polling_active = polling_is_active(settings.max_poll_state_path, settings.max_poll_timeout) if max_adapter.mode == "REAL" else False
        groups = []
        try:
            poll_state = json.loads(Path(settings.max_poll_state_path).read_text())
            groups = [
                {
                    "house_id": group.get("house_id"),
                    "last_seen_at": group.get("last_seen_at"),
                    "has_read_all_messages": group.get("has_read_all_messages"),
                }
                for group in (poll_state.get("conversations") or {}).values()
            ]
        except (OSError, ValueError, TypeError):
            pass
        return {
            "mode": max_adapter.mode,
            "connected": polling_active if max_adapter.mode == "REAL" else True,
            "api_connected": True,
            "transport": "LONG_POLLING" if max_adapter.mode == "REAL" else "SIMULATED",
            "polling_active": polling_active,
            "bot": bot,
            "groups": groups,
        }
    except MaxAdapterError as exc:
        return {"mode": max_adapter.mode, "connected": False, "api_connected": False, "polling_active": False, "error": str(exc)}


@app.get("/integrations/max/chats/{chat_id}/permissions")
async def max_permissions(chat_id: str):
    try:
        return await max_adapter.check_chat_permissions(chat_id)
    except MaxAdapterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/integrations/max/init-data/validate")
def max_init_data(payload: MaxInitDataRequest):
    if not settings.max_bot_token:
        raise HTTPException(status_code=503, detail="MAX bot token is not configured")
    try:
        return validate_max_init_data(
            payload.init_data,
            settings.max_bot_token,
            max_age_seconds=settings.max_init_data_max_age_seconds,
        )
    except MaxInitDataError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/identity/max")
def max_profile(payload: MaxInitDataRequest, db: Session = Depends(get_db)):
    user_id, role = max_identity(payload.init_data)
    profile = db.get(MaxProfile, user_id)
    return {
        "user_id": user_id,
        "role": role,
        "selected_house_id": profile.selected_house_id if profile else None,
        "residency_status": profile.residency_status if profile else None,
        "verified_resident": False,
    }


@app.post("/identity/max/house")
def select_max_house(payload: MaxHouseSelectionRequest, db: Session = Depends(get_db)):
    user_id, role = max_identity(payload.init_data)
    if not db.get(House, payload.house_id):
        not_found("House", payload.house_id)
    profile = db.get(MaxProfile, user_id)
    if profile is None:
        profile = MaxProfile(user_id=user_id, selected_house_id=payload.house_id, residency_status="SELF_DECLARED")
        db.add(profile)
    else:
        profile.selected_house_id = payload.house_id
    audit(db, "MaxProfile", user_id, "HOUSE_SELECTED", user_id, details={"house_id": payload.house_id})
    commit(db)
    return {
        "user_id": user_id,
        "role": role,
        "selected_house_id": profile.selected_house_id,
        "residency_status": profile.residency_status,
        "verified_resident": False,
    }


@app.get("/identity/max/by-user/{user_id}")
def bot_selected_house(user_id: str, request: Request, db: Session = Depends(get_db)):
    require_internal_bot(request)
    profile = db.get(MaxProfile, user_id)
    return {"selected_house_id": profile.selected_house_id if profile else None}


@app.post("/identity/max/house/by-bot")
def bot_select_house(payload: BotHouseSelectionRequest, request: Request, db: Session = Depends(get_db)):
    require_internal_bot(request)
    if not db.get(House, payload.house_id):
        not_found("House", payload.house_id)
    profile = db.get(MaxProfile, payload.user_id)
    if profile is None:
        profile = MaxProfile(user_id=payload.user_id, selected_house_id=payload.house_id, residency_status="SELF_DECLARED")
        db.add(profile)
    else:
        profile.selected_house_id = payload.house_id
    audit(db, "MaxProfile", payload.user_id, "HOUSE_SELECTED_IN_BOT", payload.user_id, details={"house_id": payload.house_id})
    commit(db)
    return {"selected_house_id": profile.selected_house_id}


@app.get("/houses")
def list_houses(db: Session = Depends(get_db)):
    return [house_dict(item) for item in db.scalars(select(House).order_by(House.id)).all()]


@app.post("/houses", status_code=201)
def add_koltsovo_house(payload: HouseCreate, request: Request, db: Session = Depends(get_db)):
    actor = authorize(request, db, roles=("resident", "representative"))
    existing = db.get(House, payload.id)
    if existing:
        if existing.address != payload.address:
            raise HTTPException(status_code=409, detail="Этот идентификатор уже занят другим домом")
        return house_dict(existing)
    house = House(
        id=payload.id,
        address=payload.address,
        region="Новосибирская область, р.п. Кольцово",
        management_org=payload.management_org,
        configuration_id=payload.id,
        metadata_json={"lat": payload.lat, "lng": payload.lng, "entrances": payload.entrances, "condition": payload.condition, "provenance": "USER", "verified": False},
    )
    db.add(house)
    db.flush()
    db.add(Zone(id=f"{house.id}-common", house_id=house.id, type="common", name="Весь дом"))
    for number in range(1, payload.entrances + 1):
        db.add(Zone(id=f"{house.id}-entrance-{number}", house_id=house.id, type="entrance", number=str(number), name=f"Подъезд {number}"))
    db.add(Zone(id=f"{house.id}-yard", house_id=house.id, type="yard", name="Двор и парковка"))
    audit(db, "House", house.id, "RESIDENT_ADDED_HOUSE", actor or "demo", details={"verified": False})
    commit(db)
    return house_dict(house)


@app.get("/houses/{house_id}")
def read_house(house_id: str, db: Session = Depends(get_db)):
    house = db.get(House, house_id) or not_found("House", house_id)
    return house_dict(house)


def operational_state(db: Session, asset: Asset) -> str:
    issues = db.scalars(select(Issue).where(Issue.asset_id == asset.id)).all()
    return operational_state_from_issues(issues, get_house_config(asset.house_id).recurrence.count)


def operational_state_from_issues(issues: list[Issue], recurrence_threshold: int) -> str:
    states = {IssueState(item.state) for item in issues}
    if IssueState.WORK_IN_PROGRESS in states:
        return "WORK_IN_PROGRESS"
    if IssueState.DONE_PENDING_VERIFICATION in states:
        return "VERIFICATION"
    if any(item.recurrence_count >= recurrence_threshold and item.state != IssueState.CLOSED.value for item in issues):
        return "RECURRING"
    if any(state not in {IssueState.CLOSED, IssueState.CANCELLED, IssueState.REJECTED, IssueState.DUPLICATE} for state in states):
        return "ACTIVE_ISSUE"
    return "HEALTHY" if issues else "UNKNOWN"


ACTIVE_ISSUE_STATES = {
    state.value
    for state in IssueState
    if state not in {IssueState.CLOSED, IssueState.CANCELLED, IssueState.REJECTED, IssueState.DUPLICATE}
}


def _issue_display_key(issue: Issue) -> tuple[str, str, str]:
    """Return the stable key used to group one active incident in House State.

    Signals can arrive repeatedly from a MAX group and older demo runs may have
    created more than one Issue row. House State is a control surface, so it
    must show one card per active asset incident while preserving the source
    issue ids for audit/detail views.
    """

    category = (issue.category or "other").lower()
    asset_key = issue.asset_id
    # A low-confidence lighting extraction can temporarily point at an
    # elevator asset. For the house overview, group it by entrance until the
    # representative resolves the exact fixture instead of showing duplicates.
    if category == "lighting" and (not asset_key or "elevator" in asset_key.lower()):
        asset_key = issue.zone_id
    symptom = (issue.symptom or "unknown").lower()
    if symptom in {"", "unknown", "proposal"}:
        symptom = "unknown"
    return (asset_key or f"category:{category}", category, symptom)


def _issue_state_priority(state: str) -> int:
    return {
        IssueState.WORK_IN_PROGRESS.value: 90,
        IssueState.ACCEPTED.value: 80,
        IssueState.SUBMITTED.value: 70,
        IssueState.DONE_PENDING_VERIFICATION.value: 65,
        IssueState.REOPENED.value: 60,
        IssueState.ACTION_READY.value: 50,
        IssueState.CONFIRMED.value: 40,
        IssueState.NEEDS_CONFIRMATION.value: 30,
        IssueState.DETECTED.value: 20,
    }.get(state, 0)


def house_state_issue_cards(
    issues: list[Issue],
    assets: list[Asset],
    zones: list[Zone],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build deduplicated active cards and a compact terminal history list."""

    asset_names = {asset.id: asset.name for asset in assets}
    zone_names = {zone.id: zone.name for zone in zones}
    groups: dict[tuple[str, str, str], list[Issue]] = {}
    history: list[dict[str, Any]] = []
    for issue in issues:
        if issue.state not in ACTIVE_ISSUE_STATES:
            history.append(issue_dict(issue))
            continue
        groups.setdefault(_issue_display_key(issue), []).append(issue)

    cards: list[dict[str, Any]] = []
    for candidates in groups.values():
        primary = max(
            candidates,
            key=lambda item: (_issue_state_priority(item.state), item.last_seen_at or item.first_seen_at),
        )
        card = issue_dict(primary)
        card.update(
            {
                "asset_name": asset_names.get(primary.asset_id),
                "zone_name": zone_names.get(primary.zone_id),
                "related_issue_count": len(candidates),
                "related_issue_ids": [item.id for item in candidates],
                "related_signal_author_ids": sorted({signal.author_id for item in candidates for signal in item.signals}),
                "signals_count": sum(len(item.signals) for item in candidates),
                # The card opens `primary`; never show another row's counters
                # as if they belonged to that issue. Legacy parallel rows stay
                # visible through the related-issue marker.
                "confirmations_count": primary.confirmations_count,
                "recurrence_count": primary.recurrence_count,
                "work_orders": [
                    {"id": order.id, "status": order.status}
                    for order in primary.work_orders
                ],
            }
        )
        cards.append(card)
    cards.sort(key=lambda item: item.get("last_seen_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    history.sort(key=lambda item: item.get("last_seen_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return cards, history[:20]


ROLE_LABELS = {
    "resident": "Житель",
    "representative": "Домоуправляющий",
    "uk": "УК / диспетчер",
    "executor": "Исполнитель",
}
ROLE_TASK_STATES = {
    "resident": {IssueState.NEEDS_CONFIRMATION.value, IssueState.DONE_PENDING_VERIFICATION.value, IssueState.REOPENED.value},
    "representative": {IssueState.NEEDS_CONFIRMATION.value, IssueState.CONFIRMED.value, IssueState.ACTION_READY.value, IssueState.REOPENED.value},
    "uk": {IssueState.SUBMITTED.value, IssueState.ACCEPTED.value, IssueState.WORK_IN_PROGRESS.value},
    "executor": {IssueState.ACCEPTED.value, IssueState.WORK_IN_PROGRESS.value, IssueState.REOPENED.value},
}


def role_task_action(issue: dict[str, Any], role: str) -> dict[str, str] | None:
    """Return the one next action the current role should see.

    This is intentionally server-side: the mini-app may hide controls for UX,
    but the API remains the source of truth for the role's queue.
    """
    state = issue.get("state")
    order = (issue.get("work_orders") or [])[-1:] if isinstance(issue.get("work_orders"), list) else []
    order_status = order[0].get("status") if order else None
    if role == "uk" and state == IssueState.ACCEPTED.value and order_status:
        return {"id": "track", "label": "Открыть назначенную работу"}
    if role == "executor" and state == IssueState.ACCEPTED.value and not order_status:
        return None
    actions: dict[tuple[str, str], tuple[str, str]] = {
        ("resident", IssueState.NEEDS_CONFIRMATION.value): ("confirm", "У меня тоже"),
        ("resident", IssueState.DONE_PENDING_VERIFICATION.value): ("verify", "Проверить результат"),
        ("resident", IssueState.REOPENED.value): ("open", "Посмотреть переоткрытую проблему"),
        ("representative", IssueState.NEEDS_CONFIRMATION.value): ("confirm", "Проверить подтверждения"),
        ("representative", IssueState.CONFIRMED.value): ("prepare", "Подготовить действие"),
        ("representative", IssueState.ACTION_READY.value): ("submit", "Передать в УК"),
        ("representative", IssueState.REOPENED.value): ("review", "Проверить повторно"),
        ("uk", IssueState.SUBMITTED.value): ("accept", "Принять обращение"),
        ("uk", IssueState.ACCEPTED.value): ("assign", "Назначить исполнителя"),
        ("uk", IssueState.WORK_IN_PROGRESS.value): ("track", "Открыть работу"),
        ("executor", IssueState.ACCEPTED.value): ("start", "Начать работу"),
        ("executor", IssueState.WORK_IN_PROGRESS.value): ("work", "Продолжить работу"),
        ("executor", IssueState.REOPENED.value): ("rework", "Начать доработку"),
    }
    if role == "executor" and state == IssueState.WORK_IN_PROGRESS.value and order_status == WorkOrderState.IN_PROGRESS.value:
        return {"id": "work", "label": "Продолжить работу"}
    selected = actions.get((role, str(state)))
    return {"id": selected[0], "label": selected[1]} if selected else None


@app.get("/houses/{house_id}/assets")
def list_assets(house_id: str, db: Session = Depends(get_db)):
    if not db.get(House, house_id):
        not_found("House", house_id)
    return [asset_dict(item, operational_state(db, item)) for item in db.scalars(select(Asset).where(Asset.house_id == house_id)).all()]


@app.get("/houses/{house_id}/state")
def house_state(
    house_id: str,
    request: Request,
    viewer_id: str | None = Query(default=None, max_length=100),
    role: str = Query(default="resident", pattern="^(resident|representative|uk|executor)$"),
    db: Session = Depends(get_db),
):
    house = db.get(House, house_id) or not_found("House", house_id)
    if settings.auth_mode == "required":
        internal_key = request.headers.get("x-dompuls-internal-key", "")
        internal = bool(settings.internal_api_key and hmac.compare_digest(internal_key, settings.internal_api_key))
        if not internal:
            init_data = request.headers.get("x-max-init-data", "")
            if init_data:
                viewer_id, role = max_identity(init_data)
                profile = db.get(MaxProfile, viewer_id)
                if not profile or profile.selected_house_id != house_id:
                    viewer_id, role = None, "resident"
            else:
                viewer_id, role = None, "resident"
    issues = db.scalars(
        select(Issue)
        .where(Issue.house_id == house_id)
        .options(selectinload(Issue.asset), selectinload(Issue.signals), selectinload(Issue.work_orders))
    ).all()
    assets = db.scalars(select(Asset).where(Asset.house_id == house_id)).all()
    zones = db.scalars(select(Zone).where(Zone.house_id == house_id)).all()
    initiatives = db.scalars(select(Initiative).where(Initiative.house_id == house_id, Initiative.state != InitiativeState.CLOSED.value)).all()
    issue_cards, history_issues = house_state_issue_cards(issues, assets, zones)
    my_issue_cards = (
        [item for item in issue_cards if viewer_id and viewer_id in (item.get("related_signal_author_ids") or [])]
        if viewer_id
        else []
    )
    if viewer_id:
        my_issue_cards.extend(
            issue_dict(item)
            for item in issues
            if item.state not in ACTIVE_ISSUE_STATES and any(signal.author_id == viewer_id for signal in item.signals)
        )
        my_issue_cards.sort(key=lambda item: item.get("last_seen_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    author_ids = {card["id"]: set(card.get("related_signal_author_ids") or []) for card in issue_cards}
    for card in issue_cards:
        card.pop("related_signal_author_ids", None)
    # Compact cards carry work-order status so the queue does not offer a
    # second assignment after a work order has already been created.
    task_pool = issue_cards if role == "resident" and viewer_id else ([] if role == "resident" else issue_cards)
    my_tasks = []
    for card in task_pool:
        action = role_task_action(card, role)
        if action:
            if role == "resident":
                already_reported = viewer_id in author_ids.get(card["id"], set())
                if action["id"] == "confirm" and already_reported:
                    continue
                if action["id"] in {"verify", "open"} and not already_reported:
                    continue
            my_tasks.append({**card, "next_action": action})
    threshold = get_house_config(house_id).recurrence.count
    issues_by_asset: dict[str, list[Issue]] = {}
    for item in issues:
        if item.asset_id:
            issues_by_asset.setdefault(item.asset_id, []).append(item)
    recent_signals = db.scalars(
        select(Signal).where(Signal.house_id == house_id).order_by(Signal.created_at.desc()).limit(40)
    ).all()
    if settings.auth_mode == "required" and viewer_id is None:
        recent_signals = []
    signal_feed = []
    for item in recent_signals:
        linked_issue = db.scalar(select(Issue).join(Issue.signals).where(Signal.id == item.id))
        if linked_issue is None and item.ai_actionability_score is not None and item.ai_actionability_score < 0.4:
            continue
        signal_feed.append(
            {
                **signal_dict(item),
                "status": "CLUSTERED" if linked_issue else "AWAITING_CONTEXT",
                "issue": (
                    {"id": linked_issue.id, "title": linked_issue.title, "state": linked_issue.state}
                    if linked_issue
                    else None
                ),
            }
        )
        if len(signal_feed) >= 12:
            break
    work_states = {IssueState.ACCEPTED.value, IssueState.WORK_IN_PROGRESS.value}
    submitted_states = {IssueState.SUBMITTED.value}
    confirmation_states = {IssueState.NEEDS_CONFIRMATION.value}
    representative_states = {IssueState.ACTION_READY.value, IssueState.CONFIRMED.value}
    verification_states = {IssueState.DONE_PENDING_VERIFICATION.value}
    return {
        "house": house_dict(house),
        "metrics": {
            "active_issues": len(issue_cards),
            # ACCEPTED means the management company has accepted the request
            # and is processing it, even before an executor starts the order.
            "work_in_progress": sum(item.get("state") in work_states for item in issue_cards),
            "awaiting_confirmation": sum(item.get("state") in confirmation_states for item in issue_cards),
            "awaiting_representative": sum(item.get("state") in representative_states for item in issue_cards),
            "submitted_to_management": sum(item.get("state") in submitted_states for item in issue_cards),
            "awaiting_verification": sum(item.get("state") in verification_states for item in issue_cards),
            "recurring_issues": sum(item.get("recurrence_count", 0) >= threshold for item in issue_cards),
            "initiatives": len(initiatives),
        },
        "assets": [asset_dict(item, operational_state_from_issues(issues_by_asset.get(item.id, []), threshold)) for item in assets],
        "zones": [zone_dict(item) for item in zones],
        "issues": issue_cards,
        "my_issues": my_issue_cards,
        "viewer": {"id": viewer_id, "role": role, "role_label": ROLE_LABELS[role]},
        "my_tasks": my_tasks[:12],
        "history_issues": history_issues,
        "initiatives": [initiative_dict(item) for item in initiatives],
        "recent_signals": signal_feed,
        "integration": {"max": max_adapter.mode, "external_submission": "SIMULATED"},
    }


def recent_unlinked_context(db: Session, signal: Signal) -> list[Signal]:
    """Return a small, ordered conversation window that is still awaiting classification."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    query = (
        select(Signal)
        .outerjoin(IssueSignal, IssueSignal.signal_id == Signal.id)
        .where(
            Signal.house_id == signal.house_id,
            Signal.id != signal.id,
            Signal.created_at >= cutoff,
            IssueSignal.issue_id.is_(None),
        )
        .order_by(Signal.created_at.desc())
        .limit(4)
    )
    if signal.chat_id:
        query = query.where(Signal.chat_id == signal.chat_id)
    else:
        query = query.where(Signal.chat_id.is_(None), Signal.author_id == signal.author_id)
    return list(reversed(db.scalars(query).all()))


def contextual_extraction(db: Session, signal: Signal, extraction):
    """Resolve split group-chat phrases without letting unrelated chatter drive state."""
    if extraction.intent not in {"noise", "issue"}:
        return extraction, [signal], signal.text
    if extraction.intent == "issue" and "zone" not in extraction.missing_fields:
        return extraction, [signal], signal.text
    for pending in reversed(recent_unlinked_context(db, signal)):
        try:
            pending_extraction = extract_structured(pending.text)
        except AIPipelineUnavailable:
            continue
        if pending_extraction.intent != "issue" or not pending_extraction.actionable:
            continue
        combined_text = f"{pending.text}\n{signal.text}"
        combined = extract_structured(combined_text)
        if combined.intent == "issue" and combined.actionable and "zone" not in combined.missing_fields:
            return combined, [pending, signal], combined_text
    return extraction, [signal], signal.text


def attach_signals(issue: Issue, signals: list[Signal]) -> int:
    existing_ids = {item.id for item in issue.signals}
    existing_authors = {item.author_id for item in issue.signals}
    added = [item for item in signals if item.id not in existing_ids]
    issue.signals.extend(added)
    return len({item.author_id for item in added if item.author_id not in existing_authors})


CATEGORY_NAMES = {
    "elevator": "Лифт",
    "lighting": "Освещение",
    "water": "Водоснабжение",
    "heating": "Отопление",
    "cleaning": "Уборка",
    "door": "Дверь и домофон",
    "parking": "Парковка",
    "other": "Общая зона",
}


def inferred_asset(db: Session, house_id: str, zone: Zone | None, category: str) -> Asset | None:
    """Create a clearly marked candidate asset for resident-added houses only."""
    if not house_id.startswith("koltsovo-") or zone is None or category == "other":
        return None
    asset_id = f"{zone.id}-{category}"
    asset = db.get(Asset, asset_id)
    if asset is None:
        asset = Asset(
            id=asset_id,
            house_id=house_id,
            zone_id=zone.id,
            type=category,
            name=f"{CATEGORY_NAMES.get(category, category)} · {zone.name}",
            attributes={"provenance": "AI_INFERENCE", "verified": False},
        )
        db.add(asset)
        db.flush()
    return asset


def recent_conversation_issue(db: Session, signal: Signal) -> Issue | None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    active_states = [
        IssueState.NEEDS_CONFIRMATION.value,
        IssueState.CONFIRMED.value,
        IssueState.ACTION_READY.value,
        IssueState.SUBMITTED.value,
        IssueState.ACCEPTED.value,
        IssueState.WORK_IN_PROGRESS.value,
    ]
    query = (
        select(Issue)
        .join(Issue.signals)
        .where(Issue.house_id == signal.house_id, Issue.state.in_(active_states), Issue.last_seen_at >= cutoff)
        .order_by(Issue.last_seen_at.desc())
    )
    if signal.chat_id:
        query = query.where(Signal.chat_id == signal.chat_id)
    else:
        query = query.where(Signal.chat_id.is_(None), Signal.author_id == signal.author_id)
    # A short follow-up is safe to attach only when this conversation has one
    # unambiguous active incident. Never bind it to an arbitrary latest issue.
    candidates = db.scalars(query.limit(10)).unique().all()
    distinct_assets = {(item.zone_id, item.asset_id, item.category) for item in candidates}
    return candidates[0] if len(distinct_assets) == 1 else None


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
    db.flush()
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
    extraction, context_signals, context_text = contextual_extraction(db, signal, extraction)
    signal.ai_actionability_score = extraction.confidence
    lowered = payload.text.lower()
    followup_markers = ("у меня тоже", "подтвержда", "вчера", "снова", "опять", "не работ")
    ambiguous_followup = extraction.intent in {"noise", "confirmation"} or (
        extraction.intent == "issue" and extraction.category == "other" and "zone" in extraction.missing_fields
    )
    if ambiguous_followup and any(marker in lowered for marker in followup_markers):
        conversation_issue = recent_conversation_issue(db, signal)
        if conversation_issue:
            conversation_issue.confirmations_count += attach_signals(conversation_issue, [signal])
            conversation_issue.last_seen_at = datetime.now(timezone.utc)
            audit(
                db,
                "Issue",
                conversation_issue.id,
                "CONVERSATION_FOLLOWUP_CLUSTERED",
                payload.author_id,
                details={"signal_id": signal.id, "chat_id": signal.chat_id},
            )
            commit(db)
            return {
                "signal": signal_dict(signal),
                "classification": extraction.model_dump(),
                "issue": issue_dict(conversation_issue),
                "clustered": True,
                "contextual_followup": True,
            }
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
            candidate.confirmations_count += attach_signals(candidate, context_signals)
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
            candidate.confirmations_count += attach_signals(candidate, context_signals)
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
    asset = resolution.asset or inferred_asset(db, payload.house_id, db.get(Zone, zone_id) if zone_id else None, payload.manual_category or extraction.category)
    asset_id = asset.id if asset else None
    candidate, score = find_duplicate(db, house_id=payload.house_id, zone_id=zone_id, asset_id=asset_id, category=extraction.category, text=context_text)
    if candidate and score >= 0.78:
        candidate.confirmations_count += attach_signals(candidate, context_signals)
        candidate.last_seen_at = datetime.now(timezone.utc)
        audit(
            db,
            "Issue",
            candidate.id,
            "SIGNAL_CLUSTERED",
            payload.author_id,
            details={"score": score, "signal_ids": [item.id for item in context_signals], "contextual": len(context_signals) > 1},
        )
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
    title = (asset.name if asset else CATEGORY_NAMES.get(category, "Проблема дома")) + ": проблема"
    issue = Issue(
        house_id=payload.house_id,
        zone_id=zone_id,
        asset_id=asset_id,
        category=category,
        symptom=extraction.symptom,
        title=title,
        description=context_text,
        severity="high" if extraction.recurrence_hint or count > 1 else "medium",
        recurrence_count=count,
        signals=context_signals,
        confirmations_count=max(1, len({item.author_id for item in context_signals})),
    )
    db.add(issue)
    db.flush()
    transition_issue(db, issue, IssueState.NEEDS_CONFIRMATION, "ai-pipeline")
    commit(db)
    return {"signal": signal_dict(signal), "classification": extraction.model_dump(), "issue": issue_dict(issue), "asset_confidence": resolution.confidence}


@app.post("/signals", status_code=201)
def create_signal(payload: SignalCreate, request: Request, db: Session = Depends(get_db)):
    actor = authorize(request, db, house_id=payload.house_id, roles=("resident", "representative"))
    if actor:
        payload.author_id = actor
        payload.source_type = "max_webapp"
        payload.force_ai_failure = False
        payload = SignalCreate.model_validate(payload.model_dump())
    return process_signal(db, payload)


@app.get("/signals/{signal_id}")
def read_signal(signal_id: str, db: Session = Depends(get_db)):
    signal = db.get(Signal, signal_id) or not_found("Signal", signal_id)
    return signal_dict(signal)


@app.post("/signals/{signal_id}/resolve")
def resolve_signal(signal_id: str, payload: ManualResolveRequest, request: Request, db: Session = Depends(get_db)):
    """Finish a signal after the AI fallback asked the user for context.

    The original signal is reused instead of creating a second synthetic signal.
    This keeps provenance, idempotency and the chat history intact while still
    allowing the resident to choose the category/zone when confidence is low.
    """
    signal = db.get(Signal, signal_id) or not_found("Signal", signal_id)
    authorize(request, db, house_id=signal.house_id, roles=("resident", "representative"), owner_id=signal.author_id)
    zone = db.get(Zone, payload.zone_id)
    if not zone or zone.house_id != signal.house_id:
        raise HTTPException(status_code=409, detail="Zone does not belong to signal house")
    asset = None
    if payload.asset_id:
        asset = db.get(Asset, payload.asset_id)
        if not asset or asset.house_id != signal.house_id or asset.zone_id != zone.id:
            raise HTTPException(status_code=409, detail="Asset does not belong to selected zone")
    if not asset:
        asset = db.scalar(
            select(Asset)
            .where(Asset.house_id == signal.house_id, Asset.zone_id == zone.id, Asset.type == payload.category)
            .order_by(Asset.name)
        )
    if not asset:
        asset = inferred_asset(db, signal.house_id, zone, payload.category)
    signal.ai_actionability_score = signal.ai_actionability_score or 0.5
    candidate, score = find_duplicate(
        db,
        house_id=signal.house_id,
        zone_id=zone.id,
        asset_id=asset.id if asset else None,
        category=payload.category,
        text=signal.text,
    )
    if candidate and score >= 0.78:
        candidate.confirmations_count += attach_signals(candidate, [signal])
        candidate.last_seen_at = datetime.now(timezone.utc)
        audit(db, "Issue", candidate.id, "MANUAL_SIGNAL_CLUSTERED", signal.author_id, details={"signal_id": signal.id, "score": score})
        commit(db)
        return {"signal": signal_dict(signal), "issue": issue_dict(candidate, detailed=True), "clustered": True, "resolved_manually": True}
    recurrence = recurrence_count(db, signal.house_id, asset.id if asset else None, payload.category)
    issue = Issue(
        house_id=signal.house_id,
        zone_id=zone.id,
        asset_id=asset.id if asset else None,
        category=payload.category,
        symptom="unknown",
        title=f"{asset.name if asset else CATEGORY_NAMES.get(payload.category, 'Проблема дома')}: проблема",
        description=signal.text,
        severity="high" if recurrence > 1 else "medium",
        recurrence_count=recurrence,
        signals=[signal],
        confirmations_count=1,
    )
    db.add(issue)
    db.flush()
    transition_issue(db, issue, IssueState.NEEDS_CONFIRMATION, signal.author_id)
    audit(db, "Issue", issue.id, "MANUAL_SIGNAL_RESOLVED", signal.author_id, details={"signal_id": signal.id})
    commit(db)
    return {"signal": signal_dict(signal), "issue": issue_dict(issue, detailed=True), "resolved_manually": True}


@app.post("/signals/{signal_id}/resolve-duplicate")
def resolve_duplicate(signal_id: str, payload: DuplicateResolutionRequest, request: Request, db: Session = Depends(get_db)):
    signal = db.get(Signal, signal_id) or not_found("Signal", signal_id)
    actor = authorize(request, db, house_id=signal.house_id, roles=("resident", "representative"), owner_id=signal.author_id)
    if actor:
        payload.actor_id = actor
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
def read_issue(issue_id: str, request: Request, db: Session = Depends(get_db)):
    issue = get_issue(db, issue_id)
    if settings.auth_mode == "required" and not request.headers.get("x-max-init-data") and not request.headers.get("x-dompuls-internal-key"):
        return issue_dict(issue)
    authorize(request, db, house_id=issue.house_id)
    result = issue_dict(issue, detailed=True)
    if issue.state in ACTIVE_ISSUE_STATES:
        siblings = [
            item.id
            for item in db.scalars(select(Issue).where(Issue.house_id == issue.house_id, Issue.id != issue.id, Issue.state.in_(ACTIVE_ISSUE_STATES))).all()
            if _issue_display_key(item) == _issue_display_key(issue)
        ]
        result["related_issue_ids"] = siblings
        result["related_issue_count"] = 1 + len(siblings)
    return result


@app.post("/issues/{issue_id}/comments", status_code=201)
def comment_on_issue(issue_id: str, payload: IssueCommentCreate, request: Request, db: Session = Depends(get_db)):
    issue = get_issue(db, issue_id)
    actor = authorize(request, db, house_id=issue.house_id)
    if actor:
        payload.author_id = actor
        payload.author_role = settings.role_for_max_user(actor)
    comment = IssueComment(issue=issue, **payload.model_dump())
    db.add(comment)
    db.flush()
    audit(db, "Issue", issue.id, "COMMENT_ADDED", payload.author_id, details={"comment_id": comment.id, "photos": len(payload.photos)})
    commit(db)
    return issue_dict(issue, detailed=True)


@app.post("/issues/{issue_id}/confirm")
def confirm_issue(issue_id: str, payload: ConfirmRequest, request: Request, db: Session = Depends(get_db)):
    issue = get_issue(db, issue_id)
    actor = authorize(request, db, house_id=issue.house_id, roles=("representative",))
    if actor:
        payload.actor_id = actor
    run_issue_transition(db, issue, IssueState.CONFIRMED, payload.actor_id)
    issue.confirmations_count += 1
    create_action(db, issue)
    run_issue_transition(db, issue, IssueState.ACTION_READY, "domain")
    commit(db)
    return issue_dict(issue, detailed=True)


@app.post("/issues/{issue_id}/route")
def select_issue_route(issue_id: str, payload: RouteSelectionRequest, request: Request, db: Session = Depends(get_db)):
    issue = get_issue(db, issue_id)
    actor = authorize(request, db, house_id=issue.house_id, roles=("representative",))
    if actor:
        payload.actor_id = actor
    if issue.state != IssueState.ACTION_READY.value:
        raise HTTPException(status_code=409, detail="Маршрут можно выбрать только для готовой к передаче проблемы")
    if not issue.actions:
        raise HTTPException(status_code=409, detail="Для проблемы ещё не сформировано действие")
    house = db.get(House, issue.house_id) or not_found("House", issue.house_id)
    action = issue.actions[-1]
    if payload.destination == "management_org":
        action.suggested_destination = house.management_org
        action.rationale = "Адресат выбран домоуправляющим: управляющая организация дома."
    else:
        action.suggested_destination = f"Домоуправляющий · {house.address}"
        action.rationale = "Адресат выбран домоуправляющим для ручной проверки обращения."
    action.manual_destination = payload.destination
    action.confidence = 1.0
    audit(db, "Issue", issue.id, "ROUTE_SELECTED", payload.actor_id, details={"destination": payload.destination})
    commit(db)
    return issue_dict(issue, detailed=True)


@app.post("/issues/{issue_id}/prepare")
def prepare_issue_action(issue_id: str, request: Request, db: Session = Depends(get_db)):
    """Recover a confirmed issue whose action was not prepared yet."""
    issue = get_issue(db, issue_id)
    actor = authorize(request, db, house_id=issue.house_id, roles=("representative",))
    if issue.state != IssueState.CONFIRMED.value:
        raise HTTPException(status_code=409, detail="Действие можно подготовить только для подтверждённой проблемы")
    if not issue.actions:
        create_action(db, issue)
    run_issue_transition(db, issue, IssueState.ACTION_READY, actor or "representative-demo")
    commit(db)
    return issue_dict(issue, detailed=True)


@app.post("/issues/{issue_id}/resident-confirm")
def resident_confirm_issue(issue_id: str, payload: ResidentConfirmRequest, request: Request, db: Session = Depends(get_db)):
    issue = get_issue(db, issue_id)
    actor = authorize(request, db, house_id=issue.house_id, roles=("resident", "representative"))
    if actor:
        payload.actor_id = actor
    allowed = {IssueState.NEEDS_CONFIRMATION.value, IssueState.CONFIRMED.value, IssueState.ACTION_READY.value}
    if issue.state not in allowed:
        raise HTTPException(status_code=409, detail="Issue no longer accepts resident confirmations")
    existing = db.scalar(
        select(AuditEvent).where(
            AuditEvent.entity_type == "Issue",
            AuditEvent.entity_id == issue.id,
            AuditEvent.event_type == "RESIDENT_CONFIRMED",
            AuditEvent.actor_id == payload.actor_id,
        )
    )
    if existing:
        return {"issue": issue_dict(issue, detailed=True), "idempotent_replay": True}
    issue.confirmations_count += 1
    issue.last_seen_at = datetime.now(timezone.utc)
    audit(db, "Issue", issue.id, "RESIDENT_CONFIRMED", payload.actor_id)
    commit(db)
    return {"issue": issue_dict(issue, detailed=True), "idempotent_replay": False}


@app.post("/issues/{issue_id}/submit")
def submit_issue(issue_id: str, payload: SubmitRequest, request: Request, db: Session = Depends(get_db)):
    issue = get_issue(db, issue_id)
    actor = authorize(request, db, house_id=issue.house_id, roles=("representative",))
    if actor:
        payload.actor_id = actor
    if not issue.actions:
        raise HTTPException(status_code=409, detail="Issue has no confirmed action")
    action = issue.actions[-1]
    if action.confidence < 0.7 and not action.manual_destination:
        raise HTTPException(status_code=409, detail="Сначала выберите адресата вручную: маршрут пока не подтверждён")
    config = get_house_config(issue.house_id)
    # A manual route choice wins over the config routing; otherwise the
    # "Выбрать адресата" button would only repaint the label.
    if action.manual_destination == "management_org":
        house = db.get(House, issue.house_id) or not_found("House", issue.house_id)
        destination_type, destination_id = "management_org", house.management_org
    elif action.manual_destination == "representative":
        default_route = config.routing["default"]
        destination_type, destination_id = default_route.destination_type, default_route.destination
    else:
        route = config.routing.get(issue.category) or config.routing["default"]
        destination_type, destination_id = route.destination_type, route.destination
    submission = Submission(
        issue=issue,
        action_id=action.id,
        destination_type=destination_type,
        destination_id=destination_id,
        channel="demo_uk_portal",
        is_simulated=True,
    )
    db.add(submission)
    run_issue_transition(db, issue, IssueState.SUBMITTED, payload.actor_id)
    commit(db)
    return issue_dict(issue, detailed=True)


@app.post("/issues/{issue_id}/accept")
def accept_issue(issue_id: str, payload: AcceptRequest, request: Request, db: Session = Depends(get_db)):
    issue = get_issue(db, issue_id)
    actor = authorize(request, db, house_id=issue.house_id, roles=("uk",))
    if actor:
        payload.actor_id = actor
    run_issue_transition(db, issue, IssueState.ACCEPTED, payload.actor_id)
    commit(db)
    return issue_dict(issue, detailed=True)


@app.post("/issues/{issue_id}/verify")
def verify_issue(issue_id: str, payload: VerifyRequest, request: Request, db: Session = Depends(get_db)):
    issue = get_issue(db, issue_id)
    actor = authorize(request, db, house_id=issue.house_id, roles=("resident", "representative"))
    if actor:
        payload.verifier_id = actor
        payload.verifier_type = settings.role_for_max_user(actor)
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
def create_work_order(payload: WorkOrderCreate, request: Request, db: Session = Depends(get_db)):
    issue = get_issue(db, payload.issue_id)
    authorize(request, db, house_id=issue.house_id, roles=("uk",))
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
def patch_work_order(order_id: str, payload: WorkOrderPatch, request: Request, db: Session = Depends(get_db)):
    order = db.get(WorkOrder, order_id) or not_found("WorkOrder", order_id)
    actor = authorize(request, db, house_id=order.issue.house_id, roles=("executor", "uk"))
    if actor:
        payload.actor_id = actor
    if payload.status == WorkOrderState.DONE.value:
        started = order.started_at
        fresh = bool(started and any(
            item.created_at and item.created_at.replace(tzinfo=timezone.utc) >= started.replace(tzinfo=timezone.utc)
            for item in order.evidence
        ))
        if not fresh:
            raise HTTPException(status_code=409, detail="Приложите подтверждение выполненной работы в текущем цикле")
    try:
        transition_work_order(db, order, WorkOrderState(payload.status), payload.actor_id)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    commit(db)
    return work_order_dict(order)


@app.post("/work-orders/{order_id}/evidence", status_code=201)
def add_evidence(order_id: str, payload: EvidenceCreate, request: Request, db: Session = Depends(get_db)):
    order = db.get(WorkOrder, order_id) or not_found("WorkOrder", order_id)
    actor = authorize(request, db, house_id=order.issue.house_id, roles=("executor",))
    if actor:
        payload.author_id = actor
    if order.status not in {WorkOrderState.IN_PROGRESS.value, WorkOrderState.DONE.value}:
        raise HTTPException(status_code=409, detail="Evidence can only be added during or after work")
    evidence = Evidence(work_order=order, **payload.model_dump())
    db.add(evidence)
    audit(db, "WorkOrder", order.id, "EVIDENCE_ADDED", payload.author_id, details={"type": payload.type})
    commit(db)
    return work_order_dict(order)


@app.post("/initiatives", status_code=201)
def create_initiative(payload: InitiativeCreate, request: Request, db: Session = Depends(get_db)):
    authorize(request, db, house_id=payload.house_id, roles=("resident", "representative"))
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
def vote(initiative_id: str, payload: PollRequest, request: Request, db: Session = Depends(get_db)):
    initiative = db.get(Initiative, initiative_id) or not_found("Initiative", initiative_id)
    actor = authorize(request, db, house_id=initiative.house_id, roles=("resident", "representative"))
    if actor:
        payload.voter_id = actor
    if initiative.state != InitiativeState.INFORMAL_POLL.value:
        raise HTTPException(status_code=409, detail="Poll is not open")
    if payload.option not in initiative.options:
        raise HTTPException(status_code=422, detail="Unknown poll option")
    existing = db.scalar(
        select(PollVote).where(PollVote.initiative_id == initiative.id, PollVote.voter_id == payload.voter_id)
    )
    if existing:
        if existing.option != payload.option:
            raise HTTPException(status_code=409, detail="Vote has already been cast for another option")
        return initiative_dict(initiative)
    db.add(PollVote(initiative_id=initiative.id, **payload.model_dump()))
    votes = dict(initiative.votes)
    votes[payload.option] = votes.get(payload.option, 0) + 1
    initiative.votes = votes
    commit(db)
    return initiative_dict(initiative)


@app.post("/initiatives/{initiative_id}/handoff")
def handoff(initiative_id: str, payload: HandoffRequest, request: Request, db: Session = Depends(get_db)):
    initiative = db.get(Initiative, initiative_id) or not_found("Initiative", initiative_id)
    actor = authorize(request, db, house_id=initiative.house_id, roles=("representative",))
    if actor:
        payload.actor_id = actor
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
    message = parse_incoming_message(payload)
    if not message:
        return None
    return SignalCreate(
        house_id=payload.get("house_id") or settings.max_default_house_id,
        text=message.text,
        author_id=message.user_id,
        chat_id=message.chat_id,
        source_type="max_message",
        external_id=message.external_id,
        attachments=message.attachments,
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
