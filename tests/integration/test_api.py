def test_health_and_house_state(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["max_mode"] == "SIMULATED"
    state = client.get("/houses/demo-house-a/state").json()
    assert state["metrics"]["recurring_issues"] == 1
    assert len(state["assets"]) == 4


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


def test_ai_timeout_returns_manual_fallback(client):
    response = client.post("/signals", json={"house_id": "demo-house-a", "text": "сломался свет", "force_ai_failure": True})
    assert response.status_code == 201
    assert response.json()["fallback"]["type"] == "MANUAL_CLASSIFICATION"


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


def test_initiative_same_vote_is_idempotent(client):
    path = "/initiatives/seed-parking-light-initiative/poll"
    vote = {"voter_id": "max-user-42", "option": "У въезда"}
    first = client.post(path, json=vote)
    second = client.post(path, json=vote)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["votes"]["У въезда"] == first.json()["votes"]["У въезда"]
