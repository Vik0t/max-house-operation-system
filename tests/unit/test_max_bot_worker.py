import json

from app.bot_worker import PollState, format_result, help_text
from app.integrations.max_updates import parse_incoming_message, polling_is_active


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


def test_polling_health_uses_fresh_marker_file(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    modified = state_path.stat().st_mtime
    assert polling_is_active(str(state_path), 30, now=modified + 60)
    assert not polling_is_active(str(state_path), 30, now=modified + 91)
    assert not polling_is_active(str(tmp_path / "missing.json"), 30)
