from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .enums import InitiativeState, IssueState, Provenance, WorkOrderState


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class House(Base, TimestampMixin):
    __tablename__ = "houses"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    address: Mapped[str] = mapped_column(String(300))
    region: Mapped[str] = mapped_column(String(120))
    management_org: Mapped[str] = mapped_column(String(200))
    configuration_id: Mapped[str] = mapped_column(String(100), unique=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    zones: Mapped[list["Zone"]] = relationship(back_populates="house", cascade="all, delete-orphan")
    assets: Mapped[list["Asset"]] = relationship(back_populates="house", cascade="all, delete-orphan")


class Zone(Base, TimestampMixin):
    __tablename__ = "zones"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    house_id: Mapped[str] = mapped_column(ForeignKey("houses.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    parent_zone_id: Mapped[str | None] = mapped_column(ForeignKey("zones.id"), nullable=True)
    house: Mapped[House] = relationship(back_populates="zones")


class Asset(Base, TimestampMixin):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    house_id: Mapped[str] = mapped_column(ForeignKey("houses.id", ondelete="CASCADE"), index=True)
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.id"), index=True)
    type: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(160))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    house: Mapped[House] = relationship(back_populates="assets")
    issues: Mapped[list["Issue"]] = relationship(back_populates="asset")


class Signal(Base, TimestampMixin):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("source_type", "external_id", name="uq_signal_external"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    house_id: Mapped[str] = mapped_column(ForeignKey("houses.id"), index=True)
    chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    author_id: Mapped[str] = mapped_column(String(100), default="anonymous")
    source_type: Mapped[str] = mapped_column(String(30), default="manual")
    external_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    ai_actionability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    provenance: Mapped[str] = mapped_column(String(30), default=Provenance.USER.value)


class IssueSignal(Base):
    __tablename__ = "issue_signals"
    issue_id: Mapped[str] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"), primary_key=True)


class Issue(Base, TimestampMixin):
    __tablename__ = "issues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    house_id: Mapped[str] = mapped_column(ForeignKey("houses.id"), index=True)
    zone_id: Mapped[str | None] = mapped_column(ForeignKey("zones.id"), nullable=True, index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(60), index=True)
    symptom: Mapped[str] = mapped_column(String(80), default="unknown")
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    state: Mapped[str] = mapped_column(String(50), default=IssueState.DETECTED.value, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    confirmations_count: Mapped[int] = mapped_column(Integer, default=1)
    recurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    provenance: Mapped[str] = mapped_column(String(30), default=Provenance.AI_INFERENCE.value)
    asset: Mapped[Asset | None] = relationship(back_populates="issues")
    signals: Mapped[list[Signal]] = relationship(secondary="issue_signals")
    actions: Mapped[list["Action"]] = relationship(back_populates="issue", cascade="all, delete-orphan")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="issue", cascade="all, delete-orphan")
    work_orders: Mapped[list["WorkOrder"]] = relationship(back_populates="issue", cascade="all, delete-orphan")
    verifications: Mapped[list["Verification"]] = relationship(back_populates="issue", cascade="all, delete-orphan")


class Action(Base, TimestampMixin):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    issue_id: Mapped[str] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(80), default="service_request")
    suggested_destination: Mapped[str] = mapped_column(String(200))
    rationale: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    requires_human_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    # Machine-readable manual choice from POST /issues/{id}/route
    # ("management_org" | "representative" | None). Submit honors it; without
    # this the representative's button only changed the label while the
    # submission always followed the config routing.
    manual_destination: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provenance: Mapped[str] = mapped_column(String(30), default=Provenance.CALCULATED.value)
    issue: Mapped[Issue] = relationship(back_populates="actions")


class Submission(Base, TimestampMixin):
    __tablename__ = "submissions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    issue_id: Mapped[str] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("actions.id"))
    destination_type: Mapped[str] = mapped_column(String(60))
    destination_id: Mapped[str] = mapped_column(String(120))
    channel: Mapped[str] = mapped_column(String(60), default="demo_portal")
    status: Mapped[str] = mapped_column(String(40), default="SENT")
    external_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    issue: Mapped[Issue] = relationship(back_populates="submissions")


class WorkOrder(Base, TimestampMixin):
    __tablename__ = "work_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    issue_id: Mapped[str] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    assignee_type: Mapped[str] = mapped_column(String(50), default="contractor")
    assignee_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(220))
    instructions: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(30), default="normal")
    status: Mapped[str] = mapped_column(String(40), default=WorkOrderState.NEW.value)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issue: Mapped[Issue] = relationship(back_populates="work_orders")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="work_order", cascade="all, delete-orphan")


class Evidence(Base, TimestampMixin):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    work_order_id: Mapped[str] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    author_id: Mapped[str] = mapped_column(String(100))
    uri: Mapped[str] = mapped_column(String(500))
    comment: Mapped[str] = mapped_column(Text, default="")
    provenance: Mapped[str] = mapped_column(String(30), default=Provenance.USER.value)
    work_order: Mapped[WorkOrder] = relationship(back_populates="evidence")


class Verification(Base, TimestampMixin):
    __tablename__ = "verifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    issue_id: Mapped[str] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    verifier_type: Mapped[str] = mapped_column(String(40))
    verifier_id: Mapped[str] = mapped_column(String(100))
    result: Mapped[str] = mapped_column(String(40))
    comment: Mapped[str] = mapped_column(Text, default="")
    issue: Mapped[Issue] = relationship(back_populates="verifications")


class Initiative(Base, TimestampMixin):
    __tablename__ = "initiatives"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    house_id: Mapped[str] = mapped_column(ForeignKey("houses.id"), index=True)
    zone_id: Mapped[str | None] = mapped_column(ForeignKey("zones.id"), nullable=True)
    related_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(220))
    summary: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSON, default=list)
    votes: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    informal_poll_state: Mapped[str] = mapped_column(String(40), default="NOT_STARTED")
    requires_formal_process: Mapped[bool] = mapped_column(Boolean, default=False)
    formal_handoff_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str] = mapped_column(String(50), default=InitiativeState.DETECTED.value)
    provenance: Mapped[str] = mapped_column(String(30), default=Provenance.AI_INFERENCE.value)


class PollVote(Base, TimestampMixin):
    __tablename__ = "poll_votes"
    __table_args__ = (UniqueConstraint("initiative_id", "voter_id", name="uq_poll_voter"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    initiative_id: Mapped[str] = mapped_column(ForeignKey("initiatives.id", ondelete="CASCADE"), index=True)
    voter_id: Mapped[str] = mapped_column(String(100))
    option: Mapped[str] = mapped_column(String(220))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[str] = mapped_column(String(80), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    actor_id: Mapped[str] = mapped_column(String(100), default="system")
    from_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), default="MAX")
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="PROCESSED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

