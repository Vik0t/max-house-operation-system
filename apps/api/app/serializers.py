from .models import Action, Asset, AuditEvent, Evidence, House, Initiative, Issue, Signal, Submission, Verification, WorkOrder, Zone


def zone_dict(zone: Zone | None):
    return None if zone is None else {"id": zone.id, "type": zone.type, "number": zone.number, "name": zone.name}


def house_dict(house: House):
    return {
        "id": house.id,
        "address": house.address,
        "region": house.region,
        "management_org": house.management_org,
        "configuration_id": house.configuration_id,
        "metadata": house.metadata_json,
    }


def asset_dict(asset: Asset, operational_state: str | None = None):
    return {
        "id": asset.id,
        "house_id": asset.house_id,
        "zone_id": asset.zone_id,
        "type": asset.type,
        "name": asset.name,
        "attributes": asset.attributes,
        "operational_state": operational_state,
    }


def signal_dict(signal: Signal):
    return {
        "id": signal.id,
        "house_id": signal.house_id,
        "chat_id": signal.chat_id,
        "author_id": signal.author_id,
        "source_type": signal.source_type,
        "text": signal.text,
        "attachments": signal.attachments,
        "ai_actionability_score": signal.ai_actionability_score,
        "provenance": signal.provenance,
        "created_at": signal.created_at,
    }


def action_dict(action: Action):
    return {
        "id": action.id,
        "type": action.type,
        "suggested_destination": action.suggested_destination,
        "manual_destination": action.manual_destination,
        "rationale": action.rationale,
        "confidence": action.confidence,
        "requires_human_confirmation": action.requires_human_confirmation,
        "provenance": action.provenance,
    }


def submission_dict(submission: Submission):
    return {
        "id": submission.id,
        "destination_type": submission.destination_type,
        "destination_id": submission.destination_id,
        "channel": submission.channel,
        "status": submission.status,
        "is_simulated": submission.is_simulated,
        "sent_at": submission.sent_at,
    }


def evidence_dict(evidence: Evidence):
    return {
        "id": evidence.id,
        "type": evidence.type,
        "author_id": evidence.author_id,
        "uri": evidence.uri,
        "comment": evidence.comment,
        "provenance": evidence.provenance,
        "created_at": evidence.created_at,
    }


def work_order_dict(order: WorkOrder):
    return {
        "id": order.id,
        "issue_id": order.issue_id,
        "asset_id": order.asset_id,
        "assignee_type": order.assignee_type,
        "assignee_id": order.assignee_id,
        "title": order.title,
        "instructions": order.instructions,
        "priority": order.priority,
        "status": order.status,
        "assigned_at": order.assigned_at,
        "started_at": order.started_at,
        "completed_at": order.completed_at,
        "evidence": [evidence_dict(item) for item in order.evidence],
    }


def verification_dict(verification: Verification):
    return {
        "id": verification.id,
        "verifier_type": verification.verifier_type,
        "result": verification.result,
        "comment": verification.comment,
        "created_at": verification.created_at,
    }


def issue_dict(issue: Issue, *, detailed: bool = False):
    data = {
        "id": issue.id,
        "house_id": issue.house_id,
        "zone_id": issue.zone_id,
        "asset_id": issue.asset_id,
        "asset_name": issue.asset.name if issue.asset else None,
        "category": issue.category,
        "symptom": issue.symptom,
        "title": issue.title,
        "description": issue.description,
        "severity": issue.severity,
        "state": issue.state,
        "first_seen_at": issue.first_seen_at,
        "last_seen_at": issue.last_seen_at,
        "confirmations_count": issue.confirmations_count,
        "recurrence_count": issue.recurrence_count,
        "provenance": issue.provenance,
    }
    if detailed:
        data.update(
            signals=[signal_dict(item) for item in sorted(issue.signals, key=lambda signal: signal.created_at)],
            actions=[action_dict(item) for item in issue.actions],
            submissions=[submission_dict(item) for item in issue.submissions],
            work_orders=[work_order_dict(item) for item in issue.work_orders],
            verifications=[verification_dict(item) for item in issue.verifications],
        )
    return data


def initiative_dict(initiative: Initiative):
    return {
        "id": initiative.id,
        "house_id": initiative.house_id,
        "zone_id": initiative.zone_id,
        "related_asset_id": initiative.related_asset_id,
        "title": initiative.title,
        "summary": initiative.summary,
        "options": initiative.options,
        "votes": initiative.votes,
        "informal_poll_state": initiative.informal_poll_state,
        "requires_formal_process": initiative.requires_formal_process,
        "formal_handoff_type": initiative.formal_handoff_type,
        "state": initiative.state,
        "provenance": initiative.provenance,
    }


def audit_dict(event: AuditEvent):
    return {
        "id": event.id,
        "event_type": event.event_type,
        "actor_id": event.actor_id,
        "from_state": event.from_state,
        "to_state": event.to_state,
        "details": event.details,
        "created_at": event.created_at,
    }
