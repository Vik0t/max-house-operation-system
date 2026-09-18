from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai.pipeline import duplicate_score
from .config_loader import get_house_config
from .enums import InitiativeState, IssueState, WorkOrderState
from .models import Action, AuditEvent, Issue, WorkOrder
from .state_machine import (
    INITIATIVE_TRANSITIONS,
    ISSUE_TRANSITIONS,
    WORK_ORDER_TRANSITIONS,
    require_transition,
)


def audit(
    db: Session,
    entity_type: str,
    entity_id: str,
    event_type: str,
    actor_id: str,
    from_state: str | None = None,
    to_state: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_id=actor_id,
            from_state=from_state,
            to_state=to_state,
            details=details or {},
        )
    )


def transition_issue(db: Session, issue: Issue, target: IssueState, actor_id: str) -> None:
    current = IssueState(issue.state)
    require_transition(current, target, ISSUE_TRANSITIONS)
    issue.state = target.value
    audit(db, "Issue", issue.id, "STATE_TRANSITION", actor_id, current.value, target.value)


def transition_work_order(db: Session, order: WorkOrder, target: WorkOrderState, actor_id: str) -> None:
    current = WorkOrderState(order.status)
    require_transition(current, target, WORK_ORDER_TRANSITIONS)
    order.status = target.value
    now = datetime.now(timezone.utc)
    if target == WorkOrderState.ASSIGNED:
        order.assigned_at = now
    elif target == WorkOrderState.IN_PROGRESS:
        order.started_at = now
        issue = order.issue
        if IssueState(issue.state) in {IssueState.ACCEPTED, IssueState.REOPENED}:
            transition_issue(db, issue, IssueState.WORK_IN_PROGRESS, actor_id)
    elif target == WorkOrderState.DONE:
        order.completed_at = now
        transition_issue(db, order.issue, IssueState.DONE_PENDING_VERIFICATION, actor_id)
    audit(db, "WorkOrder", order.id, "STATE_TRANSITION", actor_id, current.value, target.value)


def transition_initiative(db: Session, initiative, target: InitiativeState, actor_id: str) -> None:
    current = InitiativeState(initiative.state)
    require_transition(current, target, INITIATIVE_TRANSITIONS)
    initiative.state = target.value
    audit(db, "Initiative", initiative.id, "STATE_TRANSITION", actor_id, current.value, target.value)


def find_duplicate(
    db: Session,
    *,
    house_id: str,
    zone_id: str | None,
    asset_id: str | None,
    category: str,
    text: str,
) -> tuple[Issue | None, float]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    candidates = db.scalars(
        select(Issue).where(
            Issue.house_id == house_id,
            Issue.last_seen_at >= cutoff,
            Issue.state.notin_([IssueState.CLOSED.value, IssueState.CANCELLED.value, IssueState.REJECTED.value]),
        )
    ).all()
    scored = [
        (issue, duplicate_score(issue, house_id=house_id, zone_id=zone_id, asset_id=asset_id, category=category, text=text))
        for issue in candidates
    ]
    return max(scored, key=lambda pair: pair[1], default=(None, 0.0))


def recurrence_count(db: Session, house_id: str, asset_id: str | None, category: str) -> int:
    if not asset_id:
        return 1
    config = get_house_config(house_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.recurrence.window_days)
    previous = db.scalars(
        select(Issue).where(
            Issue.house_id == house_id,
            Issue.asset_id == asset_id,
            Issue.category == category,
            Issue.first_seen_at >= cutoff,
        )
    ).all()
    return len(previous) + 1


def create_action(db: Session, issue: Issue) -> Action:
    config = get_house_config(issue.house_id)
    route = config.routing.get(issue.category) or config.routing["default"]
    action = Action(
        issue=issue,
        type=route.action_type,
        suggested_destination=route.destination,
        rationale=route.rationale,
        confidence=0.98 if issue.category in config.routing else 0.55,
        requires_human_confirmation=True,
    )
    db.add(action)
    return action

