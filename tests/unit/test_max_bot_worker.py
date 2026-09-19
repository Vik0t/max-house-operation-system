import asyncio
import json

from app.bot_worker import PollState, format_result, handle_callback, help_text, initiative_keyboard, issue_keyboard, notify_state_changes
from app.integrations.max_updates import IncomingMaxCallback, parse_incoming_callback, parse_incoming_message, polling_is_active


def sample_update(text: str = "лифт опять встал"):
    return {
        "update_type": "message_created",
        "timestamp": 1770000000000,
        "message": {
            "sender": {"user_id": 42, "is_bot": False},
            "recipient": {"chat_id": 77},
            "body": {"mid": "max-1", "text": text, "attachments": [{"type": "image"}]},
        },
    }


def test_parse_incoming_max_message():
    message = parse_incoming_message(sample_update())
    assert message is not None
    assert message.text == "лифт опять встал"
    assert message.user_id == "42"
    assert message.chat_id == "77"
    assert message.external_id == "max-1"
    assert message.conversation_key == "chat:77"


def test_parse_ignores_non_message_updates():
    assert parse_incoming_message({"update_type": "bot_started"}) is None
    update = sample_update("  ")
    assert parse_incoming_message(update) is None


def test_parse_callback_update():
    callback = parse_incoming_callback(
        {
            "update_type": "message_callback",
            "callback": {"callback_id": "cb-1", "payload": "confirm_issue:issue-1", "user": {"user_id": 42}},
            "message": {"recipient": {"chat_id": 77}},
        }
    )
    assert callback == IncomingMaxCallback("cb-1", "confirm_issue:issue-1", "42", "77")


def test_poll_state_persists_marker_and_house(tmp_path):
    path = tmp_path / "bot-state.json"
    message = parse_incoming_message(sample_update())
    state = PollState(str(path), "demo-house-a")
    state.set_house(message, "demo-house-b")
    state.set_marker(123)
    restored = PollState(str(path), "demo-house-a")
    assert restored.marker == 123
    assert restored.house_for(message) == "demo-house-b"
    assert json.loads(path.read_text())["marker"] == 123


def test_poll_state_persists_issue_watchers(tmp_path):
    path = tmp_path / "bot-state.json"
    message = parse_incoming_message(sample_update())
    state = PollState(str(path), "demo-house-a")
    state.watch_issue(message, {"id": "issue-1", "state": "NEEDS_CONFIRMATION"})
    restored = PollState(str(path), "demo-house-a")
    assert restored.watchers["issue-1"]["chat:77"]["last_state"] == "NEEDS_CONFIRMATION"


def test_bot_response_exposes_real_domain_result():
    response = format_result(
        {
            "issue": {
                "title": "Лифт №2: проблема",
                "asset_name": "Лифт №2",
                "state": "NEEDS_CONFIRMATION",
                "confirmations_count": 8,
                "recurrence_count": 4,
            },
            "clustered": True,
        },
        "https://demo.example/",
    )
    assert "Лифт №2" in response
    assert "Подтверждений: 8" in response
    assert "4 событий" in response
    assert "https://demo.example/" in response


def test_help_documents_house_switching():
    response = help_text("demo-house-a")
    assert "/house_a" in response
    assert "/house_b" in response
    assert "demo-house-a" in response


def test_issue_keyboard_uses_real_max_callbacks_and_open_app():
    attachments = issue_keyboard(
        {"id": "issue-1", "state": "DONE_PENDING_VERIFICATION"},
        "https://example.test/app/",
        "dompuls_bot",
    )
    buttons = attachments[0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "verify_yes:issue-1"
    assert buttons[0][1]["payload"] == "verify_no:issue-1"
    assert buttons[1][0] == {"type": "open_app", "text": "Открыть карточку", "web_app": "dompuls_bot", "payload": "issue_issue-1"}


def test_initiative_keyboard_maps_options_to_stable_indexes():
    attachments = initiative_keyboard({"id": "initiative-1", "options": ["Да", "Нет"]}, "dompuls_bot")
    buttons = attachments[0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "vote:initiative-1:0"
    assert buttons[1][0]["payload"] == "vote:initiative-1:1"


def test_confirm_callback_updates_max_message_and_subscribes_chat(tmp_path):
    class Adapter:
        answer = None

        async def answer_callback(self, callback_id, **kwargs):
            self.answer = {"callback_id": callback_id, **kwargs}

    class Api:
        async def resident_confirm(self, issue_id, actor_id):
            assert (issue_id, actor_id) == ("issue-1", "42")
            return {
                "issue": {
                    "id": issue_id,
                    "title": "Лифт №2: проблема",
                    "state": "NEEDS_CONFIRMATION",
                    "confirmations_count": 9,
                    "recurrence_count": 4,
                },
                "idempotent_replay": False,
            }

    adapter = Adapter()
    state = PollState(str(tmp_path / "bot-state.json"), "demo-house-a")
    asyncio.run(
        handle_callback(
            adapter,
            Api(),
            IncomingMaxCallback("cb-1", "confirm_issue:issue-1", "42", "77"),
            "https://example.test/app/",
            "dompuls_bot",
            state,
        )
    )
    assert adapter.answer["notification"] == "Подтверждение учтено"
    assert "Подтверждений: 9" in adapter.answer["message"]["text"]
    assert state.watchers["issue-1"]["chat:77"]["user_id"] == "42"


def test_state_change_sends_verification_buttons(tmp_path):
    class Adapter:
        sent = []

        async def send_message(self, **kwargs):
            self.sent.append(kwargs)

    class Api:
        async def issue(self, issue_id):
            return {"id": issue_id, "title": "Лифт №2", "state": "DONE_PENDING_VERIFICATION"}

    state = PollState(str(tmp_path / "bot-state.json"), "demo-house-a")
    state.watchers = {
        "issue-1": {"chat:77": {"chat_id": "77", "user_id": "42", "last_state": "WORK_IN_PROGRESS"}}
    }
    adapter = Adapter()
    asyncio.run(notify_state_changes(adapter, Api(), state, "https://example.test/app/", "dompuls_bot"))
    assert "WORK_IN_PROGRESS → DONE_PENDING_VERIFICATION" in adapter.sent[0]["text"]
    buttons = adapter.sent[0]["attachments"][0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "verify_yes:issue-1"


def test_polling_health_uses_fresh_marker_file(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    modified = state_path.stat().st_mtime
    assert polling_is_active(str(state_path), 30, now=modified + 60)
    assert not polling_is_active(str(state_path), 30, now=modified + 91)
    assert not polling_is_active(str(tmp_path / "missing.json"), 30)
