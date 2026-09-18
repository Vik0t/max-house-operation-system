import pytest

from app.enums import InitiativeState, IssueState, WorkOrderState
from app.state_machine import (
    INITIATIVE_TRANSITIONS,
    ISSUE_TRANSITIONS,
    WORK_ORDER_TRANSITIONS,
    InvalidTransition,
    require_transition,
)


def test_issue_happy_path_is_explicit():
    path = [
        IssueState.DETECTED,
        IssueState.NEEDS_CONFIRMATION,
        IssueState.CONFIRMED,
        IssueState.ACTION_READY,
        IssueState.SUBMITTED,
        IssueState.ACCEPTED,
        IssueState.WORK_IN_PROGRESS,
        IssueState.DONE_PENDING_VERIFICATION,
        IssueState.VERIFIED,
        IssueState.CLOSED,
    ]
    for current, target in zip(path, path[1:]):
        require_transition(current, target, ISSUE_TRANSITIONS)


def test_issue_impossible_transition_is_rejected():
    with pytest.raises(InvalidTransition, match="DETECTED -> CLOSED"):
        require_transition(IssueState.DETECTED, IssueState.CLOSED, ISSUE_TRANSITIONS)


def test_reopen_transition_is_supported():
    require_transition(IssueState.DONE_PENDING_VERIFICATION, IssueState.REOPENED, ISSUE_TRANSITIONS)
    require_transition(IssueState.REOPENED, IssueState.WORK_IN_PROGRESS, ISSUE_TRANSITIONS)


def test_work_order_and_initiative_paths():
    require_transition(WorkOrderState.ASSIGNED, WorkOrderState.IN_PROGRESS, WORK_ORDER_TRANSITIONS)
    require_transition(WorkOrderState.DONE, WorkOrderState.REWORK_REQUIRED, WORK_ORDER_TRANSITIONS)
    require_transition(InitiativeState.RESULT, InitiativeState.FORMAL_HANDOFF_REQUIRED, INITIATIVE_TRANSITIONS)

