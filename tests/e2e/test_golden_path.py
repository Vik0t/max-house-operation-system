from app.seed import reset_and_seed


def close_issue(client, verify_result="confirmed"):
    issue_id = "demo-current-elevator-issue"
    issue = client.post(f"/issues/{issue_id}/confirm", json={}).json()
    assert issue["state"] == "ACTION_READY"
    issue = client.post(f"/issues/{issue_id}/submit", json={}).json()
    assert issue["submissions"][-1]["is_simulated"] is True
    issue = client.post(f"/issues/{issue_id}/accept", json={}).json()
    assert issue["state"] == "ACCEPTED"
    order = client.post("/work-orders", json={"issue_id": issue_id}).json()
    assert order["status"] == "ASSIGNED"
    order = client.patch(f"/work-orders/{order['id']}", json={"status": "IN_PROGRESS"}).json()
    assert order["status"] == "IN_PROGRESS"
    order = client.post(
        f"/work-orders/{order['id']}/evidence",
        json={"type": "after_photo", "uri": "/demo/elevator-after.svg", "comment": "Исправлено"},
    ).json()
    assert len(order["evidence"]) == 1
    client.patch(f"/work-orders/{order['id']}", json={"status": "DONE"})
    issue = client.post(f"/issues/{issue_id}/verify", json={"result": verify_result}).json()
    return issue, order["id"]


def test_golden_path_is_stable_for_20_clean_runs(client):
    for run in range(20):
        if run:
            reset_and_seed(reset=True)
        issue, _ = close_issue(client)
        assert issue["state"] == "CLOSED"
        timeline = client.get("/assets/house-a-elevator-2/timeline").json()
        assert timeline["asset"]["operational_state"] == "HEALTHY"
        assert any(event.get("id") == "demo-current-elevator-issue" for event in timeline["events"])


def test_negative_verification_reopens_and_requests_rework(client):
    issue, order_id = close_issue(client, verify_result="rejected")
    assert issue["state"] == "REOPENED"
    order = next(item for item in issue["work_orders"] if item["id"] == order_id)
    assert order["status"] == "REWORK_REQUIRED"

    restarted = client.patch(f"/work-orders/{order_id}", json={"status": "IN_PROGRESS"})
    assert restarted.status_code == 200
    assert client.get(f"/issues/{issue['id']}").json()["state"] == "WORK_IN_PROGRESS"
    stale_done = client.patch(f"/work-orders/{order_id}", json={"status": "DONE"})
    assert stale_done.status_code == 409
    fresh = client.post(f"/work-orders/{order_id}/evidence", json={
        "type": "after_photo", "uri": "/demo/elevator-after.svg", "comment": "Повторная проверка",
    })
    assert fresh.status_code == 201
    assert client.patch(f"/work-orders/{order_id}", json={"status": "DONE"}).status_code == 200
    assert client.post(f"/issues/{issue['id']}/verify", json={"result": "confirmed"}).json()["state"] == "CLOSED"


def test_initiative_flow_to_formal_marker(client):
    initiative_id = "seed-parking-light-initiative"
    vote = client.post(f"/initiatives/{initiative_id}/poll", json={"voter_id": "new-resident", "option": "У въезда"})
    assert vote.status_code == 200
    result = client.post(f"/initiatives/{initiative_id}/handoff", json={}).json()
    assert result["state"] == "FORMAL_HANDOFF_REQUIRED"
    assert result["formal_handoff_type"] == "OSS_PREPARATION"


def test_second_house_uses_its_own_config(client):
    signal = client.post("/signals", json={"house_id": "demo-house-b", "text": "лифт не работает в первом подъезде"}).json()
    issue_id = signal["issue"]["id"]
    confirmed = client.post(f"/issues/{issue_id}/confirm", json={}).json()
    assert confirmed["actions"][-1]["suggested_destination"] == "polar-lift-contractor"
    assert "подрядчик" in confirmed["actions"][-1]["rationale"].lower()
