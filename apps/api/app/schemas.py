from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ExtractedZone(BaseModel):
    type: str | None = None
    number: str | None = None


class StructuredExtraction(BaseModel):
    actionable: bool
    intent: Literal["issue", "initiative", "confirmation", "noise"]
    category: str = "other"
    zone: ExtractedZone = Field(default_factory=ExtractedZone)
    asset_hint: str | None = None
    symptom: str = "unknown"
    recurrence_hint: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class SignalCreate(BaseModel):
    house_id: str
    text: str = Field(min_length=1, max_length=4000)
    author_id: str = Field(default="resident-demo", max_length=100)
    chat_id: str | None = Field(default=None, max_length=100)
    source_type: Literal["max_message", "bot_dialog", "manual", "imported"] = "manual"
    external_id: str | None = Field(default=None, max_length=160)
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    manual_category: str | None = None
    manual_zone_id: str | None = None
    force_ai_failure: bool = False


class ConfirmRequest(BaseModel):
    actor_id: str = "resident-demo"


class ResidentConfirmRequest(BaseModel):
    actor_id: str = Field(default="resident-demo", min_length=1, max_length=100)


class SubmitRequest(BaseModel):
    actor_id: str = "representative-demo"


class AcceptRequest(BaseModel):
    actor_id: str = "uk-demo"


class VerifyRequest(BaseModel):
    verifier_type: Literal["resident", "representative", "uk", "system"] = "resident"
    verifier_id: str = "resident-demo"
    result: Literal["confirmed", "rejected", "partially_confirmed"]
    comment: str = Field(default="", max_length=1000)


class WorkOrderCreate(BaseModel):
    issue_id: str
    assignee_id: str = "master-demo"
    title: str | None = None
    instructions: str = ""
    priority: Literal["low", "normal", "high", "urgent"] = "high"


class WorkOrderPatch(BaseModel):
    status: Literal["ASSIGNED", "IN_PROGRESS", "DONE", "ACCEPTED", "REWORK_REQUIRED"]
    actor_id: str = "executor-demo"


class EvidenceCreate(BaseModel):
    type: Literal["before_photo", "after_photo", "document", "comment", "measurement"]
    author_id: str = "executor-demo"
    uri: str = Field(min_length=1, max_length=500)
    comment: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def safe_uri(self):
        allowed = ("https://", "http://", "/demo/", "data:image/")
        if not self.uri.startswith(allowed):
            raise ValueError("Evidence URI must be http(s), /demo/, or a data image")
        return self


class InitiativeCreate(BaseModel):
    house_id: str
    title: str = Field(min_length=3, max_length=220)
    summary: str = Field(min_length=3, max_length=2000)
    zone_id: str | None = None
    related_asset_id: str | None = None
    options: list[str] = Field(min_length=2, max_length=5)
    requires_formal_process: bool = False


class PollRequest(BaseModel):
    voter_id: str
    option: str


class HandoffRequest(BaseModel):
    actor_id: str = "representative-demo"
    handoff_type: str = "OSS_PREPARATION"


class ManualResolveRequest(BaseModel):
    category: str
    zone_id: str
    asset_id: str | None = None


class RouteSelectionRequest(BaseModel):
    destination: Literal["management_org", "representative"]
    actor_id: str = Field(default="representative-demo", min_length=1, max_length=100)


class DuplicateResolutionRequest(BaseModel):
    candidate_issue_id: str
    decision: Literal["LINK", "CREATE_NEW"]
    actor_id: str = "resident-demo"


class MaxWebhook(BaseModel):
    event_id: str
    chat_id: str
    user_id: str
    house_id: str
    text: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class MaxInitDataRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=16_000)
