"""MAX identity, house onboarding and the role boundary between surfaces."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from app.ai.runtime_model import load_model, predict_category
from app.main import settings


def signed_init_data(user_id: int, token: str) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id, "first_name": "Тест"}, ensure_ascii=False, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_max_house_selection_persists_across_miniapp_and_bot(client, monkeypatch):
    monkeypatch.setattr(settings, "max_bot_token", "test-bot-token")
    monkeypatch.setattr(settings, "internal_api_key", "bot-internal-test")
    init_data = signed_init_data(501, "test-bot-token")
    initial = client.post("/identity/max", json={"init_data": init_data})
    assert initial.status_code == 200
    assert initial.json()["selected_house_id"] is None

    selected = client.post("/identity/max/house", json={"init_data": init_data, "house_id": "demo-house-a"})
    assert selected.status_code == 200
    assert selected.json()["residency_status"] == "SELF_DECLARED"
    assert selected.json()["verified_resident"] is False
    assert client.get("/identity/max/by-user/501").status_code == 401
    headers = {"X-Dompuls-Internal-Key": "bot-internal-test"}
    assert client.get("/identity/max/by-user/501", headers=headers).json()["selected_house_id"] == "demo-house-a"
    changed = client.post("/identity/max/house/by-bot", headers=headers, json={"user_id": "501", "house_id": "demo-house-b"})
    assert changed.status_code == 200
    assert client.post("/identity/max", json={"init_data": init_data}).json()["selected_house_id"] == "demo-house-b"


def test_required_auth_prevents_forged_role_and_wrong_house(client, monkeypatch):
    monkeypatch.setattr(settings, "max_bot_token", "test-bot-token")
    monkeypatch.setattr(settings, "auth_mode", "required")
    init_data = signed_init_data(502, "test-bot-token")
    body = {"house_id": "demo-house-b", "text": "лифт не работает в первом подъезде", "author_id": "someone-else"}
    assert client.post("/signals", json=body).status_code == 401
    headers = {"X-Max-Init-Data": init_data}
    assert client.post("/signals", headers=headers, json=body).status_code == 403
    assert client.post("/identity/max/house", json={"init_data": init_data, "house_id": "demo-house-b"}).status_code == 200
    created = client.post("/signals", headers=headers, json=body)
    assert created.status_code == 201
    assert created.json()["signal"]["author_id"] == "502"
    state = client.get("/houses/demo-house-b/state", headers=headers, params={"role": "uk", "viewer_id": "someone-else"}).json()
    assert state["viewer"] == {"id": "502", "role": "resident", "role_label": "Житель"}
    issue_id = created.json()["issue"]["id"]
    assert client.post(f"/issues/{issue_id}/accept", headers=headers, json={}).status_code == 403


def test_public_asset_history_hides_work_photos_and_executor_identity(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "required")
    monkeypatch.setattr(settings, "internal_api_key", "bot-internal-test")
    public = client.get("/assets/house-a-elevator-2/timeline")
    assert public.status_code == 200
    public_works = [event for event in public.json()["events"] if event["type"] == "work_order"]
    public_issues = [event for event in public.json()["events"] if event["type"] == "issue"]
    assert public_issues[0]["description"] == "Подробности доступны после входа через MAX."
    assert public_works and public_works[0]["evidence_count"] == 1
    assert public_works[0]["evidence"] == []
    assert "assignee_id" not in public_works[0]
    private = client.get("/assets/house-a-elevator-2/timeline", headers={"X-Dompuls-Internal-Key": "bot-internal-test"})
    assert private.status_code == 200
    private_works = [event for event in private.json()["events"] if event["type"] == "work_order"]
    assert private_works[0]["evidence"][0]["uri"] == "/demo/elevator-after.svg"


def test_public_house_and_issue_cards_hide_freeform_resident_text(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "required")
    monkeypatch.setattr(settings, "internal_api_key", "bot-internal-test")
    public = client.get("/houses/demo-house-a/state").json()
    assert public["issues"] and all(item["description"] == "Подробности доступны после входа через MAX." for item in public["issues"])
    assert client.get("/issues/demo-current-elevator-issue").json()["description"] == "Подробности доступны после входа через MAX."
    assert all(item["description"] == "Подробности доступны после входа через MAX." for item in client.get("/issues", params={"house_id": "demo-house-a"}).json())
    private = client.get("/issues/demo-current-elevator-issue", headers={"X-Dompuls-Internal-Key": "bot-internal-test"}).json()
    assert private["description"] == "Лифт опять встал во втором подъезде."


def test_max_status_does_not_report_legacy_dialogs_as_groups(client, monkeypatch, tmp_path):
    import app.main as main
    from app.integrations.max_adapter import MockMaxAdapter

    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"conversations": {
        "chat:old-dialog": {"house_id": "demo-house-a", "last_seen_at": "old"},
        "chat:real-group": {"house_id": "demo-house-b", "last_seen_at": "recent", "has_read_all_messages": True},
    }}), encoding="utf-8")
    monkeypatch.setattr(main.settings, "max_poll_state_path", str(state_file))
    monkeypatch.setattr(main, "max_adapter", MockMaxAdapter())
    response = client.get("/integrations/max/status")
    assert response.status_code == 200
    assert response.json()["groups"] == [{"house_id": "demo-house-b", "last_seen_at": "recent", "has_read_all_messages": True}]


def test_koltsovo_house_is_created_without_core_code_change(client):
    added = client.post("/houses", json={
        "id": "koltsovo-test-7", "address": "Никольский проспект, 7, р.п. Кольцово",
        "lat": 54.94, "lng": 83.19, "entrances": 3,
        "management_org": "Не подтверждена",
    })
    assert added.status_code == 201
    house_id = added.json()["id"]
    state = client.get(f"/houses/{house_id}/state").json()
    assert [zone["name"] for zone in state["zones"]] == ["Весь дом", "Подъезд 1", "Подъезд 2", "Подъезд 3", "Двор и парковка"]
    issue = client.post("/signals", json={"house_id": house_id, "text": "лифт не работает в третьем подъезде"})
    assert issue.status_code == 201
    assert issue.json()["issue"]["zone_id"] == f"{house_id}-entrance-3"
    assert client.post("/houses", json={"id": "outside-test", "address": "Москва, 1", "lat": 54.94, "lng": 83.19}).status_code == 422


def test_runtime_model_artifact_is_available_without_pickle():
    model = load_model()
    assert model and model["kind"] == "tfidf_char_lr"
    assert len(model["classes"]) == 7
    prediction = predict_category("мусор в подвале")
    assert prediction is not None and prediction[0] == "cleaning"


def test_uncertain_route_requires_representative_choice(client):
    house_id = "koltsovo-route-1"
    assert client.post("/houses", json={
        "id": house_id, "address": "Рассветная, 9, р.п. Кольцово", "lat": 54.94, "lng": 83.19,
    }).status_code == 201
    created = client.post("/signals", json={"house_id": house_id, "text": "окно разбито в первом подъезде"}).json()
    issue_id = created["issue"]["id"]
    confirmed = client.post(f"/issues/{issue_id}/confirm", json={})
    assert confirmed.status_code == 200
    assert confirmed.json()["actions"][-1]["confidence"] < 0.7
    assert client.post(f"/issues/{issue_id}/submit", json={}).status_code == 409
    chosen = client.post(f"/issues/{issue_id}/route", json={"destination": "representative"})
    assert chosen.status_code == 200
    submitted = client.post(f"/issues/{issue_id}/submit", json={})
    assert submitted.status_code == 200
    assert submitted.json()["submissions"][-1]["is_simulated"] is True


def test_external_assistant_only_receives_latest_manual_message(client, monkeypatch):
    import app.main as main

    sent = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "Могу помочь с обращением."}}]}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **kwargs):
            sent.update(kwargs["json"])
            return FakeResponse()

    monkeypatch.setattr(settings, "max_bot_token", "test-bot-token")
    monkeypatch.setattr(settings, "llm_mode", "openrouter")
    monkeypatch.setattr(settings, "llm_api_key", "test-provider-key")
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeClient)
    body = {"messages": [
        {"role": "user", "content": "мой прошлый адрес"},
        {"role": "assistant", "content": "не пересылать ответ помощника"},
        {"role": "user", "content": "Как пожаловаться? Позвоните +7 999 123 45 67, test@example.com"},
    ], "house_id": "demo-house-a"}
    assert client.post("/assistant/chat", json=body).json()["mode"] == "LOCAL_RULES"
    assert not sent
    reply = client.post("/assistant/chat", json=body, headers={"X-Max-Init-Data": signed_init_data(711, "test-bot-token")})
    assert reply.status_code == 200 and reply.json()["mode"] == "OPENROUTER"
    assert len(sent["messages"]) == 2
    assert sent["messages"][1] == {"role": "user", "content": "Как пожаловаться? Позвоните [телефон скрыт], [электронная почта скрыта]"}
