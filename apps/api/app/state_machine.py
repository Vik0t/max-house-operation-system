from enum import StrEnum

from .enums import InitiativeState, IssueState, WorkOrderState


class InvalidTransition(ValueError):
    pass


ISSUE_TRANSITIONS: dict[IssueState, set[IssueState]] = {
    IssueState.DETECTED: {IssueState.NEEDS_CONFIRMATION, IssueState.DUPLICATE, IssueState.REJECTED, IssueState.CANCELLED},
    IssueState.NEEDS_CONFIRMATION: {IssueState.CONFIRMED, IssueState.DUPLICATE, IssueState.REJECTED, IssueState.CANCELLED},
    IssueState.CONFIRMED: {IssueState.ACTION_READY, IssueState.CANCELLED},
    IssueState.ACTION_READY: {IssueState.SUBMITTED, IssueState.CANCELLED},
    IssueState.SUBMITTED: {IssueState.ACCEPTED, IssueState.REJECTED, IssueState.CANCELLED},
    IssueState.ACCEPTED: {IssueState.WORK_IN_PROGRESS, IssueState.CANCELLED},
    IssueState.WORK_IN_PROGRESS: {IssueState.DONE_PENDING_VERIFICATION, IssueState.CANCELLED},
    IssueState.DONE_PENDING_VERIFICATION: {IssueState.VERIFIED, IssueState.REOPENED},
    IssueState.VERIFIED: {IssueState.CLOSED},
    IssueState.REOPENED: {IssueState.ACTION_READY, IssueState.WORK_IN_PROGRESS, IssueState.CANCELLED},
}

WORK_ORDER_TRANSITIONS: dict[WorkOrderState, set[WorkOrderState]] = {
    WorkOrderState.NEW: {WorkOrderState.ASSIGNED},
    WorkOrderState.ASSIGNED: {WorkOrderState.IN_PROGRESS},
    WorkOrderState.IN_PROGRESS: {WorkOrderState.DONE},
    WorkOrderState.DONE: {WorkOrderState.ACCEPTED, WorkOrderState.REWORK_REQUIRED},
    WorkOrderState.REWORK_REQUIRED: {WorkOrderState.IN_PROGRESS},
}

INITIATIVE_TRANSITIONS: dict[InitiativeState, set[InitiativeState]] = {
    InitiativeState.DETECTED: {InitiativeState.DRAFT},
    InitiativeState.DRAFT: {InitiativeState.DISCUSSION},
    InitiativeState.DISCUSSION: {InitiativeState.INFORMAL_POLL},
    InitiativeState.INFORMAL_POLL: {InitiativeState.RESULT},
    InitiativeState.RESULT: {InitiativeState.CLOSED, InitiativeState.FORMAL_HANDOFF_REQUIRED},
}


def require_transition(current: StrEnum, target: StrEnum, transitions: dict) -> None:
    if target not in transitions.get(current, set()):
        raise InvalidTransition(f"Impossible transition: {current.value} -> {target.value}")

