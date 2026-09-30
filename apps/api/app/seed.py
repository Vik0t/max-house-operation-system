import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from .config_loader import load_all_configs
from .db import Base, SessionLocal, engine
from .enums import InitiativeState, IssueState, Provenance, WorkOrderState
from .models import Asset, Evidence, House, Initiative, Issue, Signal, Verification, WorkOrder, Zone


def seed_configs(session) -> None:
    for config in load_all_configs():
        session.add(
            House(
                id=config.house.id,
                address=config.house.address,
                region=config.house.region,
                management_org=config.house.management_org,
                configuration_id=config.house.id,
                metadata_json=config.house.metadata,
            )
        )
    session.flush()
    for config in load_all_configs():
        for zone in config.zones:
            session.add(
                Zone(
                    id=zone.id,
                    house_id=config.house.id,
                    type=zone.type,
                    number=zone.number,
                    name=zone.name,
                    parent_zone_id=zone.parent,
                )
            )
    session.flush()
    for config in load_all_configs():
        for asset in config.assets:
            session.add(
                Asset(
                    id=asset.id,
                    house_id=config.house.id,
                    zone_id=asset.zone,
                    type=asset.type,
                    name=asset.name,
                    attributes=asset.attributes,
                )
            )
    session.flush()


def seed_history(session) -> None:
    now = datetime.now(timezone.utc)
    incident_days = [15, 34, 76]
    for index, days_ago in enumerate(incident_days, start=1):
        occurred = now - timedelta(days=days_ago)
        issue = Issue(
            id=f"seed-elevator-incident-{index}",
            house_id="demo-house-a",
            zone_id="house-a-entrance-2",
            asset_id="house-a-elevator-2",
            category="elevator",
            symptom="not_working",
            title="Лифт №2: остановка",
            description=f"Исторический инцидент лифта №2 ({days_ago} дней назад)",
            severity="high",
            state=IssueState.CLOSED.value,
            first_seen_at=occurred,
            last_seen_at=occurred + timedelta(hours=4),
            confirmations_count=3 + index,
            recurrence_count=index,
            provenance=Provenance.SYNTHETIC.value,
        )
        order = WorkOrder(
            id=f"seed-elevator-work-{index}",
            issue=issue,
            asset_id="house-a-elevator-2",
            assignee_id="lift-service-a",
            title="Диагностика и восстановление лифта №2",
            instructions="Проверить привод, двери и журнал ошибок.",
            priority="high",
            status=WorkOrderState.ACCEPTED.value,
            assigned_at=occurred + timedelta(minutes=25),
            started_at=occurred + timedelta(hours=1),
            completed_at=occurred + timedelta(hours=3),
        )
        order.evidence.append(
            Evidence(
                id=f"seed-elevator-evidence-{index}",
                type="after_photo",
                author_id="master-demo",
                uri="/demo/elevator-after.svg",
                comment="Лифт запущен, тестовый прогон выполнен.",
                provenance=Provenance.SYNTHETIC.value,
                created_at=occurred + timedelta(hours=3),
            )
        )
        issue.verifications.append(
            Verification(
                id=f"seed-elevator-verification-{index}",
                verifier_type="resident",
                verifier_id="resident-demo",
                result="confirmed",
                comment="Работает.",
                created_at=occurred + timedelta(hours=4),
            )
        )
        session.add(issue)
    current_signals = [
        Signal(
            id="seed-current-signal-1",
            house_id="demo-house-a",
            chat_id="demo-house-chat",
            author_id="resident-seed-1",
            source_type="imported",
            external_id="seed-chat-001",
            text="лифт снова остановился",
            attachments=[{"type": "image", "uri": "/demo/elevator-before.svg"}],
            ai_actionability_score=0.96,
            provenance=Provenance.SYNTHETIC.value,
            created_at=now - timedelta(minutes=18),
        ),
        Signal(
            id="seed-current-signal-2",
            house_id="demo-house-a",
            chat_id="demo-house-chat",
            author_id="resident-seed-2",
            source_type="imported",
            external_id="seed-chat-002",
            text="второй подъезд, прикладываю фото панели",
            attachments=[{"type": "image", "uri": "/demo/elevator-panel.svg"}],
            ai_actionability_score=0.88,
            provenance=Provenance.SYNTHETIC.value,
            created_at=now - timedelta(minutes=15),
        ),
    ]
    session.add(
        Issue(
            id="demo-current-elevator-issue",
            house_id="demo-house-a",
            zone_id="house-a-entrance-2",
            asset_id="house-a-elevator-2",
            category="elevator",
            symptom="not_working",
            title="Лифт №2: не работает",
            description="Лифт опять встал во втором подъезде.",
            severity="high",
            state=IssueState.NEEDS_CONFIRMATION.value,
            first_seen_at=now - timedelta(minutes=18),
            last_seen_at=now - timedelta(minutes=15),
            confirmations_count=5,
            recurrence_count=4,
            provenance=Provenance.AI_INFERENCE.value,
            signals=current_signals,
        )
    )
    session.add(
        Initiative(
            id="seed-parking-light-initiative",
            house_id="demo-house-a",
            zone_id="house-a-yard",
            related_asset_id="house-a-parking-light",
            title="Второй фонарь на парковке",
            summary="Жители предлагают установить дополнительный фонарь у въезда на парковку.",
            options=["У въезда", "У дальней стены", "Оставить как есть"],
            votes={"У въезда": 5, "У дальней стены": 2},
            informal_poll_state="OPEN",
            requires_formal_process=True,
            state=InitiativeState.INFORMAL_POLL.value,
            provenance=Provenance.SYNTHETIC.value,
        )
    )


def reset_and_seed(*, reset: bool = False, if_empty: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    with SessionLocal() as session:
        count = session.scalar(select(func.count()).select_from(House)) or 0
        if count:
            if if_empty:
                # Config metadata can gain non-destructive fields (for example
                # map coordinates) after a deployment without resetting work.
                for config in load_all_configs():
                    house = session.get(House, config.house.id)
                    if house:
                        house.metadata_json = {**config.house.metadata, **(house.metadata_json or {})}
                session.commit()
                return
            raise RuntimeError("Database already contains houses; use --reset for deterministic demo reset")
        seed_configs(session)
        seed_history(session)
        session.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed deterministic Дом.Среда demo data")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--if-empty", action="store_true")
    args = parser.parse_args()
    reset_and_seed(reset=args.reset, if_empty=args.if_empty)
