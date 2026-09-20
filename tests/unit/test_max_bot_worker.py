import asyncio
import json

from app.bot_worker import PollState, cancel_keyboard, format_result, format_status, handle_callback, help_text, initiative_keyboard, issue_button_label, issue_keyboard, menu_keyboard, notify_state_changes, zone_keyboard
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


def test_poll_state_registers_group_permissions(tmp_path):
    path = tmp_path / "bot-state.json"
    message = parse_incoming_message(sample_update())
    state = PollState(str(path), "demo-house-a")
    state.remember_conversation(message, {"permissions": ["read_all_messages"], "has_read_all_messages": True})
    restored = PollState(str(path), "demo-house-a")
    group = restored.conversations["chat:77"]
    assert group["chat_id"] == "77"
    assert group["has_read_all_messages"] is True


def test_poll_state_roles_are_per_user_and_persist(tmp_path):
    path = tmp_path / "bot-state.json"
    state = PollState(str(path), "demo-house-a")
    state.set_role("chat:77", "42", "uk")
    restored = PollState(str(path), "demo-house-a")
    assert restored.role_for("chat:77", "42") == "uk"
    assert restored.role_for("chat:77", "99") == "resident"


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


def test_user_facing_labels_do_not_leak_internal_category_names():
    issue = {
        "id": "issue-1",
        "title": "Lighting: проблема",
        "asset_name": "Lighting",
        "state": "NEEDS_CONFIRMATION",
        "confirmations_count": 3,
    }
    assert "Освещение" in issue_button_label(issue)
    assert "Lighting" not in issue_button_label(issue)
    rendered = format_result({"issue": issue}, "https://demo.example/")
    assert "Освещение" in rendered
    assert "Lighting" not in rendered
    wrong_asset = {**issue, "title": "Лифт №1: проблема", "asset_name": "Лифт №1", "category": "lighting"}
    assert "Освещение" in issue_button_label(wrong_asset)
    assert "Лифт №1" not in issue_button_label(wrong_asset)


def test_house_status_is_grouped_by_lifecycle_and_role_next_step():
    rendered = format_status(
        {
            "house": {"address": "Никольский проспект, 12"},
            "metrics": {
                "active_issues": 2,
                "work_in_progress": 1,
                "awaiting_confirmation": 1,
                "awaiting_verification": 0,
                "recurring_issues": 1,
                "initiatives": 0,
            },
            "issues": [
                {"id": "issue-1", "asset_name": "Лифт №2", "state": "NEEDS_CONFIRMATION", "confirmations_count": 3},
                {"id": "issue-2", "asset_name": "Освещение", "state": "ACCEPTED", "confirmations_count": 2},
            ],
        },
        role="representative",
    )
    assert "Требуют подтверждений (1)" in rendered
    assert "Приняты управляющей компанией (1)" in rendered
    assert "домоуправляющий" in rendered


def test_help_documents_house_switching():
    response = help_text("demo-house-a")
    assert "/дом_a" in response
    assert "/дом_b" in response
    assert "demo-house-a" not in response


def test_menu_exposes_chat_first_product_actions():
    buttons = menu_keyboard()[0]["payload"]["buttons"]
    payloads = {button["payload"] for row in buttons for button in row}
    assert {"menu:report", "menu:status", "menu:initiative", "menu:houses"} <= payloads


def test_issue_keyboard_exposes_real_lifecycle_actions():
    buttons = issue_keyboard({"id": "issue-1", "state": "ACTION_READY"}, "", "dompuls_bot")[0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "issue_submit:issue-1"
    buttons = issue_keyboard(
        {
            "id": "issue-1",
            "state": "IN_PROGRESS",
            "work_orders": [{"id": "order-1", "status": "IN_PROGRESS", "evidence": []}],
        },
        "",
        "dompuls_bot",
    )[0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "order_evidence:issue-1"


def test_issue_keyboard_hides_operator_actions_from_resident():
    buttons = issue_keyboard({"id": "issue-1", "state": "ACTION_READY"}, "", "dompuls_bot", "resident")[0]["payload"]["buttons"]
    payloads = {button["payload"] for row in buttons for button in row if button.get("type") == "callback"}
    assert "issue_submit:issue-1" not in payloads


def test_issue_keyboard_shows_only_uk_action():
    buttons = issue_keyboard({"id": "issue-1", "state": "SUBMITTED"}, "", "dompuls_bot", "uk")[0]["payload"]["buttons"]
    payloads = {button["payload"] for row in buttons for button in row if button.get("type") == "callback"}
    assert "issue_accept:issue-1" in payloads
    assert "issue_submit:issue-1" not in payloads
    assert "issue_assign:issue-1" not in payloads


def test_navigation_buttons_have_distinct_meaning():
    cancel_buttons = cancel_keyboard()[0]["payload"]["buttons"]
    assert cancel_buttons == [[{"type": "callback", "text": "В меню", "payload": "back:menu"}]]
    zone_buttons = zone_keyboard([{"id": "zone-1", "name": "Подъезд 1"}])[0]["payload"]["buttons"]
    assert zone_buttons[-2][0]["text"] == "Назад к категории"
    assert zone_buttons[-1][0]["text"] == "Отменить обращение"


def test_menu_report_starts_persistent_dialog(tmp_path):
    class Adapter:
        answer = None

        async def answer_callback(self, callback_id, **kwargs):
            self.answer = kwargs

    class Api:
        pass

    state = PollState(str(tmp_path / "bot-state.json"), "demo-house-a")
    adapter = Adapter()
    asyncio.run(
        handle_callback(
            adapter,
            Api(),
            IncomingMaxCallback("cb-1", "menu:report", "42", "77"),
            "https://example.test/app/",
            "dompuls_bot",
            state,
        )
    )
    assert state.dialog("chat:77")["mode"] == "report_text"
    assert "Сообщить о проблеме" in adapter.answer["message"]["text"]


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
    assert "В работе → Ждёт проверки жителем" in adapter.sent[0]["text"]
    buttons = adapter.sent[0]["attachments"][0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "verify_yes:issue-1"


def test_polling_health_uses_fresh_marker_file(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    modified = state_path.stat().st_mtime
    assert polling_is_active(str(state_path), 30, now=modified + 60)
    assert not polling_is_active(str(state_path), 30, now=modified + 91)
    assert not polling_is_active(str(tmp_path / "missing.json"), 30)
