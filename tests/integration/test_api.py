def test_health_and_house_state(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["max_mode"] == "SIMULATED"
    state = client.get("/houses/demo-house-a/state").json()
    assert state["metrics"]["recurring_issues"] == 1
    assert len(state["assets"]) == 4


def test_house_state_can_scope_my_issues_without_exposing_author_ids(client):
    state = client.get("/houses/demo-house-a/state", params={"viewer_id": "resident-seed-1"}).json()
    assert [item["id"] for item in state["my_issues"]] == ["demo-current-elevator-issue"]
    assert all("related_signal_author_ids" not in item for item in state["issues"])


def test_house_state_exposes_role_specific_task_queue(client):
    resident = client.get("/houses/demo-house-a/state", params={"viewer_id": "resident-seed-1", "role": "resident"}).json()
    representative = client.get("/houses/demo-house-a/state", params={"role": "representative"}).json()
    uk = client.get("/houses/demo-house-a/state", params={"role": "uk"}).json()
    assert resident["viewer"]["role"] == "resident"
    assert all(item["state"] in {"NEEDS_CONFIRMATION", "DONE_PENDING_VERIFICATION", "REOPENED"} for item in resident["my_tasks"])
    assert all(item["next_action"]["label"] for item in representative["my_tasks"])
    assert all(item["state"] in {"SUBMITTED", "ACCEPTED", "WORK_IN_PROGRESS"} for item in uk["my_tasks"])


def test_signal_clusters_by_house_zone_asset(client):
    result = client.post("/signals", json={"house_id": "demo-house-a", "text": "лифт опять встал во втором подъезде", "author_id": "r6"})
    assert result.status_code == 201
    body = result.json()
    assert body["clustered"] is True
    assert body["issue"]["id"] == "demo-current-elevator-issue"
    assert body["issue"]["confirmations_count"] == 6

    other = client.post("/signals", json={"house_id": "demo-house-b", "text": "лифт не работает в первом подъезде"})
    assert other.status_code == 201
    assert other.json()["issue"]["house_id"] == "demo-house-b"
    assert other.json()["issue"]["id"] != body["issue"]["id"]


def test_split_group_messages_build_one_contextual_issue(client):
    first = client.post(
        "/signals",
        json={
            "house_id": "demo-house-b",
            "chat_id": "group-101",
            "author_id": "resident-1",
            "external_id": "group-101-1",
            "source_type": "max_message",
            "text": "лифт опять встал",
        },
    )
    assert first.status_code == 201
    assert first.json()["fallback"]["type"] == "ZONE_CLARIFICATION"
    assert first.json().get("issue") is None

    second = client.post(
        "/signals",
        json={
            "house_id": "demo-house-b",
            "chat_id": "group-101",
            "author_id": "resident-2",
            "external_id": "group-101-2",
            "source_type": "max_message",
            "text": "первый подъезд",
        },
    )
    assert second.status_code == 201
    issue = second.json()["issue"]
    assert issue["asset_id"] == "house-b-elevator-1"
    assert issue["confirmations_count"] == 2

    third = client.post(
        "/signals",
        json={
            "house_id": "demo-house-b",
            "chat_id": "group-101",
            "author_id": "resident-3",
            "external_id": "group-101-3",
            "source_type": "max_message",
            "text": "у меня тоже",
        },
    ).json()
    fourth = client.post(
        "/signals",
        json={
            "house_id": "demo-house-b",
            "chat_id": "group-101",
            "author_id": "resident-4",
            "external_id": "group-101-4",
            "source_type": "max_message",
            "text": "вчера уже не работал",
        },
    ).json()
    assert third["issue"]["id"] == issue["id"]
    assert fourth["issue"]["id"] == issue["id"]
    assert fourth["contextual_followup"] is True
    assert fourth["issue"]["confirmations_count"] == 4

    detailed = client.get(f"/issues/{issue['id']}").json()
    assert [item["text"] for item in detailed["signals"]] == [
        "лифт опять встал",
        "первый подъезд",
        "у меня тоже",
        "вчера уже не работал",
    ]
    state = client.get("/houses/demo-house-b/state").json()
    linked = [item for item in state["recent_signals"] if item["issue"] and item["issue"]["id"] == issue["id"]]
    assert len(linked) == 4


def test_ai_timeout_returns_manual_fallback(client):
    response = client.post("/signals", json={"house_id": "demo-house-a", "text": "сломался свет", "force_ai_failure": True})
    assert response.status_code == 201
    assert response.json()["fallback"]["type"] == "MANUAL_CLASSIFICATION"


def test_manual_resolution_reuses_original_signal(client):
    response = client.post(
        "/signals",
        json={
            "house_id": "demo-house-a",
            "text": "сломался свет у входа",
            "force_ai_failure": True,
            "external_id": "manual-resolution-1",
            "source_type": "max_message",
        },
    )
    assert response.status_code == 201
    signal_id = response.json()["signal"]["id"]
    resolved = client.post(
        f"/signals/{signal_id}/resolve",
        json={"category": "lighting", "zone_id": "house-a-entrance-1"},
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["resolved_manually"] is True
    assert body["issue"]["signals"][0]["id"] == signal_id
    assert body["issue"]["zone_id"] == "house-a-entrance-1"


def test_asset_resolution_does_not_cross_category_boundaries(client):
    response = client.post(
        "/signals",
        json={"house_id": "demo-house-a", "text": "свет в первом подъезде не работает", "author_id": "lighting-resident"},
    )
    assert response.status_code == 201
    issue = response.json()["issue"]
    assert issue["category"] == "lighting"
    assert issue["zone_id"] == "house-a-entrance-1"
    assert issue["asset_id"] is None


def test_user_can_resolve_uncertain_duplicate_both_ways(client):
    first = client.post(
        "/signals",
        json={"house_id": "demo-house-a", "text": "непонятная проблема", "force_ai_failure": True, "external_id": "manual-duplicate-1"},
    ).json()
    linked = client.post(
        f"/signals/{first['signal']['id']}/resolve-duplicate",
        json={"candidate_issue_id": "demo-current-elevator-issue", "decision": "LINK"},
    )
    assert linked.status_code == 200
    assert any(item["id"] == first["signal"]["id"] for item in linked.json()["signals"])

    second = client.post(
        "/signals",
        json={"house_id": "demo-house-a", "text": "отдельный шум в лифте", "force_ai_failure": True, "external_id": "manual-duplicate-2"},
    ).json()
    created = client.post(
        f"/signals/{second['signal']['id']}/resolve-duplicate",
        json={"candidate_issue_id": "demo-current-elevator-issue", "decision": "CREATE_NEW"},
    )
    assert created.status_code == 200
    assert created.json()["id"] != "demo-current-elevator-issue"
    assert created.json()["state"] == "NEEDS_CONFIRMATION"


def test_max_webhook_is_idempotent(client):
    update = {
        "update_type": "message_created",
        "timestamp": 1770000000000,
        "house_id": "demo-house-b",
        "message": {
            "sender": {"user_id": 42},
            "recipient": {"chat_id": 77},
            "body": {"mid": "max-message-1", "text": "лифт не работает в первом подъезде", "attachments": []},
        },
    }
    first = client.post("/integrations/max/webhook", json=update)
    second = client.post("/integrations/max/webhook", json=update)
    assert first.status_code == 200
    assert second.json()["idempotent_replay"] is True


def test_resident_confirmation_is_per_user_idempotent(client):
    path = "/issues/demo-current-elevator-issue/resident-confirm"
    first = client.post(path, json={"actor_id": "max-user-42"})
    second = client.post(path, json={"actor_id": "max-user-42"})
    assert first.status_code == 200
    assert first.json()["idempotent_replay"] is False
    assert first.json()["issue"]["confirmations_count"] == 6
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert second.json()["issue"]["confirmations_count"] == 6


def test_representative_can_select_manual_route(client):
    confirmed = client.post("/issues/demo-current-elevator-issue/confirm", json={"actor_id": "representative-demo"})
    assert confirmed.status_code == 200
    assert confirmed.json()["state"] == "ACTION_READY"
    routed = client.post(
        "/issues/demo-current-elevator-issue/route",
        json={"destination": "management_org", "actor_id": "representative-demo"},
    )
    assert routed.status_code == 200
    assert routed.json()["actions"][-1]["confidence"] == 1.0
    assert "управляющ" in routed.json()["actions"][-1]["rationale"]


def test_initiative_same_vote_is_idempotent(client):
    path = "/initiatives/seed-parking-light-initiative/poll"
    vote = {"voter_id": "max-user-42", "option": "У въезда"}
    first = client.post(path, json=vote)
    second = client.post(path, json=vote)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["votes"]["У въезда"] == first.json()["votes"]["У въезда"]
