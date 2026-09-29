import asyncio
import json

from app.bot_worker import CATEGORY_LABELS, PollState, cancel_keyboard, category_keyboard, current_role, fallback_keyboard, format_result, format_status, group_ack, handle_callback, handle_message, help_text, initiative_keyboard, is_recognized_result, issue_button_label, issue_keyboard, menu_keyboard, notify_state_changes, role_denied_text, zone_keyboard
from app.integrations.max_adapter import MaxAdapterError
from app.integrations.max_updates import IncomingMaxCallback, image_url, parse_incoming_callback, parse_incoming_message, polling_is_active


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


def test_max_dialog_chat_id_does_not_become_group_context():
    update = sample_update()
    update["message"]["recipient"] = {"chat_id": 499762541, "chat_type": "dialog", "user_id": 42}
    message = parse_incoming_message(update)
    assert message is not None
    assert message.chat_id is None
    assert message.conversation_key == "user:42"


def test_parse_ignores_non_message_updates():
    assert parse_incoming_message({"update_type": "bot_started"}) is None
    update = sample_update("  ")
    assert parse_incoming_message(update) is None


def test_parse_image_only_message_with_real_url():
    update = sample_update("  ")
    update["message"]["body"]["attachments"] = [
        {"type": "image", "payload": {"photos": {"big": {"url": "https://max.example/photo.jpg"}}}}
    ]
    message = parse_incoming_message(update)
    assert message is not None and message.text == "[Фото]"
    assert image_url(message.attachments) == "https://max.example/photo.jpg"


def test_parse_callback_update():
    callback = parse_incoming_callback(
        {
            "update_type": "message_callback",
            "callback": {"callback_id": "cb-1", "payload": "confirm_issue:issue-1", "user": {"user_id": 42}},
            "message": {"recipient": {"chat_id": 77}},
        }
    )
    assert callback == IncomingMaxCallback("cb-1", "confirm_issue:issue-1", "42", "77")


def test_max_dialog_callback_uses_user_context():
    callback = parse_incoming_callback({
        "update_type": "message_callback",
        "callback": {"callback_id": "cb-2", "payload": "menu", "user": {"user_id": 42}},
        "message": {"recipient": {"chat_id": 499762541, "chat_type": "dialog", "user_id": 42}},
    })
    assert callback == IncomingMaxCallback("cb-2", "menu", "42", None)


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


def test_assigned_bot_roles_ignore_showcase_selection(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import app.bot_worker as worker

    state = PollState(str(tmp_path / "bot-state.json"), "demo-house-a")
    state.set_role("chat:77", "42", "uk")
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(bot_role_mode="assigned", role_for_max_user=lambda user_id: "resident"))
    assert current_role(state, "chat:77", "42") == "resident"
    assert "назначает организатор" in role_denied_text("uk")


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
    assert "/мой_id" in response
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


def test_issue_keyboard_does_not_ask_reporter_to_confirm_again():
    issue = {"id": "issue-1", "state": "NEEDS_CONFIRMATION", "signals": [{"author_id": "resident-1"}]}
    own = issue_keyboard(issue, "", "dompuls_bot", "resident", viewer_id="resident-1")[0]["payload"]["buttons"]
    neighbor = issue_keyboard(issue, "", "dompuls_bot", "resident", viewer_id="resident-2")[0]["payload"]["buttons"]
    assert not any(button.get("payload") == "confirm_issue:issue-1" for row in own for button in row)
    assert any(button.get("payload") == "confirm_issue:issue-1" for row in neighbor for button in row)


def test_confirmed_issue_is_remembered_across_bot_restart(tmp_path):
    path = tmp_path / "bot-state.json"
    state = PollState(str(path), "demo-house-a")
    state.mark_confirmed("issue-1", "resident-1")
    restored = PollState(str(path), "demo-house-a")
    assert restored.has_confirmed("issue-1", "resident-1")
    assert not restored.has_confirmed("issue-1", "resident-2")


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
    assert state.dialog("user:42")["mode"] == "report_text"
    assert "Сообщить о проблеме" in adapter.answer["message"]["text"]


def test_report_dialog_belongs_to_the_author_not_the_whole_chat(tmp_path):
    class Adapter:
        def __init__(self):
            self.answer = {}

        async def answer_callback(self, callback_id, notification=None, message=None):
            self.answer = message or {}

        async def check_chat_permissions(self, chat_id):
            return {"chat_id": chat_id, "has_read_all_messages": True}

    state = PollState(str(tmp_path / "bot-state.json"), "demo-house-a")
    for user_id in ("42", "43"):
        asyncio.run(
            handle_callback(
                Adapter(),
                object(),
                IncomingMaxCallback(f"cb-{user_id}", "menu:report", user_id, "77"),
                "https://example.test/app/",
                "dompuls_bot",
                state,
            )
        )
    assert state.dialog("user:42")["mode"] == "report_text"
    assert state.dialog("user:43")["mode"] == "report_text"
    # Neither resident inherits the other's pending question, and the shared chat
    # key no longer holds a dialog at all.
    assert state.dialog("chat:77") is None


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
    # The house chat gets one short progress line, the reporter gets the card
    # with the action buttons.
    assert adapter.sent[0]["chat_id"] == "77"
    assert "user_id" not in adapter.sent[0]
    assert "В работе → Ждёт проверки жителем" in adapter.sent[0]["text"]
    assert "attachments" not in adapter.sent[0]
    assert adapter.sent[1]["user_id"] == "42"
    buttons = adapter.sent[1]["attachments"][0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "verify_yes:issue-1"


def test_polling_health_uses_fresh_marker_file(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    modified = state_path.stat().st_mtime
    assert polling_is_active(str(state_path), 30, now=modified + 60)
    assert not polling_is_active(str(state_path), 30, now=modified + 91)
    assert not polling_is_active(str(tmp_path / "missing.json"), 30)


class RecordingAdapter:
    def __init__(self, *, direct_message_fails: bool = False):
        self.sent: list[dict] = []
        self.direct_message_fails = direct_message_fails

    async def check_chat_permissions(self, chat_id):
        return {"chat_id": chat_id, "permissions": ["read_all_messages"], "has_read_all_messages": True}

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        if self.direct_message_fails and "user_id" in kwargs:
            raise MaxAdapterError("user never opened the private chat")


def run_message(adapter, api, state, text):
    message = parse_incoming_message(sample_update(text))
    asyncio.run(handle_message(adapter, api, state, message, "https://example.test/app/", "dompuls_bot"))
    return adapter.sent


def test_group_command_is_answered_privately_not_in_the_chat(tmp_path):
    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    sent = run_message(RecordingAdapter(), object(), state, "/start")
    assert sent[0]["user_id"] == "42"
    assert "chat_id" not in sent[0]


def test_max_user_id_command_is_answered_privately(tmp_path):
    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    sent = run_message(RecordingAdapter(), object(), state, "/мой_id")
    assert sent[0]["user_id"] == "42"
    assert "MAX ID: 42" in sent[0]["text"]
    assert "chat_id" not in sent[0]


def test_group_status_command_is_answered_privately(tmp_path):
    class Api:
        async def house_status(self, house_id, viewer_id=None, role="resident"):
            return {
                "house": {"address": "Никольский проспект, 12"},
                "metrics": {"active_issues": 0},
                "issues": [],
            }

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    sent = run_message(RecordingAdapter(), Api(), state, "/состояние")
    assert sent[0]["user_id"] == "42"
    assert "chat_id" not in sent[0]


def test_problem_report_stays_in_the_group_chat(tmp_path):
    class Api:
        async def process_message(self, message, house_id, **kwargs):
            return {
                "issue": {
                    "id": "issue-1",
                    "title": "Лифт №2: проблема",
                    "asset_name": "Лифт №2",
                    "state": "NEEDS_CONFIRMATION",
                    "confirmations_count": 1,
                }
            }

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    sent = run_message(RecordingAdapter(), Api(), state, "лифт не работает во втором подъезде")
    assert sent[0]["chat_id"] == "77"
    assert "user_id" not in sent[0]


def test_private_reply_falls_back_to_chat_when_direct_message_fails(tmp_path):
    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    sent = run_message(RecordingAdapter(direct_message_fails=True), object(), state, "/start")
    assert sent[0]["user_id"] == "42"
    assert sent[1]["chat_id"] == "77"
    assert "Не смог открыть личный чат" in sent[1]["text"]
    assert "Личные кнопки не показываю" in sent[1]["text"]
    assert "attachments" not in sent[1]


def test_role_chosen_privately_stays_private(tmp_path):
    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    state.set_role("user:42", "42", "uk")
    assert state.role_for("user:42", "42") == "uk"
    assert state.has_role("user:42", "42") is True
    # The house group must not inherit it: operator buttons stay hidden there
    # until the role is picked in the group itself.
    assert state.role_for("chat:77", "42") == "resident"
    assert state.has_role("chat:77", "42") is False
    assert state.role_for("chat:77", "99") == "resident"


def test_state_files_from_before_role_isolation_still_load(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"roles": {"chat:77": {"42": "uk"}}, "user_roles": {"42": "executor"}}),
        encoding="utf-8",
    )
    restored = PollState(str(path), "demo-house-a")
    # Per-conversation roles win; the legacy global fallback is ignored.
    assert restored.role_for("chat:77", "42") == "uk"
    assert restored.role_for("user:42", "42") == "resident"
    assert restored.role_for("chat:77", "99") == "resident"


def test_recognized_result_detection():
    assert is_recognized_result({"issue": {"id": "issue-1"}})
    assert is_recognized_result({"initiative": {"id": "initiative-1"}})
    assert is_recognized_result({"fallback": {"type": "ZONE_CLARIFICATION"}})
    assert is_recognized_result({"result": "CREATED"})
    assert not is_recognized_result({"result": "NO_ACTION"})
    assert not is_recognized_result({})


def test_unrecognised_group_message_is_answered_with_silence(tmp_path):
    class Api:
        async def process_message(self, message, house_id, **kwargs):
            return {"result": "NO_ACTION", "signal": {"id": "signal-1"}}

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    sent = run_message(RecordingAdapter(), Api(), state, "привет, кто идёт в магазин")
    assert sent == []
    assert state.watchers == {}


def test_unrecognised_private_message_still_gets_a_hint(tmp_path):
    class Api:
        async def process_message(self, message, house_id, **kwargs):
            return {"result": "NO_ACTION", "signal": {"id": "signal-1"}}

    message = parse_incoming_message(
        {
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 42, "is_bot": False},
                "body": {"mid": "max-dm", "text": "привет"},
            },
        }
    )
    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    adapter = RecordingAdapter()
    asyncio.run(handle_message(adapter, Api(), state, message, "https://example.test/app/", "dompuls_bot"))
    assert adapter.sent[0]["user_id"] == "42"
    assert "не увидел обращения" in adapter.sent[0]["text"]


def zone_clarification_api():
    class Api:
        async def process_message(self, message, house_id, **kwargs):
            return {
                "signal": {"id": "signal-1"},
                "classification": {"category": "lighting"},
                "fallback": {
                    "type": "ZONE_CLARIFICATION",
                    "message": "Уточните место проблемы",
                    "choices": [{"id": "zone-1", "name": "Первый подъезд"}],
                },
            }

    return Api()


def test_group_clarification_is_asked_privately_and_quotes_the_message(tmp_path):
    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    sent = run_message(RecordingAdapter(), zone_clarification_api(), state, "лампочка сломалась")
    # The group gets one line saying the report was taken and a question is
    # coming; the question itself is addressed to its author alone.
    assert len(sent) == 2
    assert sent[0]["chat_id"] == "77"
    assert "user_id" not in sent[0]
    assert "attachments" not in sent[0]
    assert sent[1]["user_id"] == "42"
    assert "chat_id" not in sent[1]
    assert "лампочка сломалась" in sent[1]["text"]


def test_group_clarification_keeps_a_dialog_the_author_can_answer_privately(tmp_path):
    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    run_message(RecordingAdapter(), zone_clarification_api(), state, "лампочка сломалась")
    dialog = state.dialog("user:42")
    assert dialog["mode"] == "report_zone"
    assert dialog["category"] == "lighting"
    assert dialog["text"] == "лампочка сломалась"
    assert state.dialog("chat:77") is None


def test_clarification_from_a_group_is_finished_by_a_button_in_the_private_chat(tmp_path):
    class Api:
        def __init__(self):
            self.processed = []
            self.resolved = []

        async def resolve_signal(self, signal_id, category, zone_id):
            self.resolved.append((signal_id, category, zone_id))
            return {"issue": {"id": "issue-1", "state": "NEEDS_CONFIRMATION"}}

    class Adapter(RecordingAdapter):
        def __init__(self):
            super().__init__()
            self.answer = {}

        async def answer_callback(self, callback_id, notification=None, message=None):
            self.answer = message or {}

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    run_message(RecordingAdapter(), zone_clarification_api(), state, "лампочка сломалась")
    api, adapter = Api(), Adapter()
    asyncio.run(
        handle_callback(
            adapter,
            api,
            IncomingMaxCallback("cb-1", "zone:zone-1", "42", None),
            "https://example.test/app/",
            "dompuls_bot",
            state,
        )
    )
    assert api.resolved == [("signal-1", "lighting", "zone-1")]
    assert state.dialog("user:42") is None


def test_group_acknowledges_a_new_problem_in_one_line_and_sends_the_card_privately(tmp_path):
    class Api:
        async def process_message(self, message, house_id, **kwargs):
            return {"issue": {"id": "issue-1", "title": "Лифт: не работает", "state": "NEEDS_CONFIRMATION"}}

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    sent = run_message(RecordingAdapter(), Api(), state, "лифт не работает во втором подъезде")
    assert len(sent) == 2
    assert sent[0]["chat_id"] == "77"
    assert sent[0]["text"].startswith("✅ Записал:")
    assert "Подробности в личке" in sent[0]["text"]
    assert "attachments" not in sent[0]
    assert sent[1]["user_id"] == "42"
    assert "chat_id" not in sent[1]
    assert "Проблема зарегистрирована" in sent[1]["text"]
    assert sent[1]["attachments"]


def test_group_initiative_publishes_a_shared_informal_poll(tmp_path):
    class Api:
        async def process_message(self, message, house_id, **kwargs):
            return {"initiative": {
                "id": "initiative-1", "title": "Второй фонарь на парковке",
                "summary": "Жители предлагают осветить парковку.",
                "state": "INFORMAL_POLL", "options": ["Поддерживаю", "Не поддерживаю"],
                "votes": {},
            }}

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    sent = run_message(RecordingAdapter(), Api(), state, "на парковке нужен второй фонарь")
    assert len(sent) == 1
    assert sent[0]["chat_id"] == "77"
    assert "user_id" not in sent[0]
    assert "Опрос жителей" in sent[0]["text"]
    buttons = sent[0]["attachments"][0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "vote:initiative-1:0"
    assert buttons[1][0]["payload"] == "vote:initiative-1:1"
    assert not any(button.get("payload", "").startswith("initiative_handoff:") for row in buttons for button in row)


def test_group_vote_updates_shared_card_without_operator_button(tmp_path):
    class Api:
        async def initiative(self, initiative_id):
            return {"id": initiative_id, "title": "Фонарь", "summary": "Осветить парковку",
                    "state": "INFORMAL_POLL", "options": ["Да", "Нет"], "votes": {}}

        async def vote(self, initiative_id, voter_id, option):
            assert (initiative_id, voter_id, option) == ("initiative-1", "42", "Да")
            return {"id": initiative_id, "title": "Фонарь", "summary": "Осветить парковку",
                    "state": "INFORMAL_POLL", "options": ["Да", "Нет"], "votes": {"Да": 1}}

    class Adapter(RecordingAdapter):
        async def answer_callback(self, callback_id, notification=None, message=None):
            self.answer = message
            self.notification = notification

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    state.set_role("chat:77", "42", "representative")
    adapter = Adapter()
    asyncio.run(handle_callback(adapter, Api(), IncomingMaxCallback("cb-1", "vote:initiative-1:0", "42", "77"), "https://example.test/app/", "dompuls_bot", state))
    assert adapter.notification == "Голос учтён"
    assert "Да — 1" in adapter.answer["text"]
    buttons = adapter.answer["attachments"][0]["payload"]["buttons"]
    assert not any(button.get("payload", "").startswith("initiative_handoff:") for row in buttons for button in row)


def test_choosing_a_zone_in_private_tells_the_house_chat_the_report_is_registered(tmp_path):
    class Api:
        async def resolve_signal(self, signal_id, category, zone_id):
            return {"issue": {"id": "issue-1", "title": "Окно разбито", "state": "NEEDS_CONFIRMATION"}}

    class Adapter(RecordingAdapter):
        def __init__(self):
            super().__init__()
            self.answer = {}

        async def answer_callback(self, callback_id, notification=None, message=None):
            self.answer = message or {}

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    run_message(RecordingAdapter(), zone_clarification_api(), state, "окно разбито на втором этаже")
    adapter = Adapter()
    asyncio.run(
        handle_callback(
            adapter,
            Api(),
            IncomingMaxCallback("cb-1", "zone:zone-1", "42", None),
            "https://example.test/app/",
            "dompuls_bot",
            state,
        )
    )
    # The card is edited in place in the private chat, and the house chat learns
    # about the registration from a separate short line.
    assert adapter.answer["text"].startswith("**Проблема зарегистрирована**")
    group_lines = [item for item in adapter.sent if item.get("chat_id") == "77"]
    assert len(group_lines) == 1
    assert group_lines[0]["text"].startswith("✅ Записал: Окно разбито")
    assert "attachments" not in group_lines[0]


def test_duplicate_decision_reported_back_to_the_house_chat(tmp_path):
    class Api:
        async def resolve_duplicate(self, signal_id, candidate_issue_id, decision, actor_id):
            return {"id": "issue-7", "title": "Освещение подъезда", "state": "NEEDS_CONFIRMATION"}

    class Adapter:
        def __init__(self):
            self.sent = []
            self.answer = {}

        async def send_message(self, **kwargs):
            self.sent.append(kwargs)

        async def answer_callback(self, callback_id, notification=None, message=None):
            self.answer = message or {}

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    state.remember_duplicate_chat("signal-9", "77")
    adapter = Adapter()
    asyncio.run(
        handle_callback(
            adapter,
            Api(),
            IncomingMaxCallback("cb-2", "duplicate:signal-9:issue-7:LINK", "42", None),
            "https://example.test/app/",
            "dompuls_bot",
            state,
        )
    )
    assert adapter.sent[0]["chat_id"] == "77"
    assert "Принял, это уже было" in adapter.sent[0]["text"]
    # The reminder is consumed, not repeated on the next press.
    assert state.pop_duplicate_chat("signal-9") is None


def test_role_picker_remembers_the_role_for_the_next_messages(tmp_path):
    class Adapter:
        def __init__(self):
            self.answer = {}

        async def answer_callback(self, callback_id, notification=None, message=None):
            self.answer = message or {}

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    adapter = Adapter()
    asyncio.run(
        handle_callback(
            adapter,
            object(),
            IncomingMaxCallback("cb-3", "role:uk", "42", "77"),
            "https://example.test/app/",
            "dompuls_bot",
            state,
        )
    )
    assert state.role_for("chat:77", "42") == "uk"
    assert state.role_for("user:42", "42") == "resident"
    assert state.has_role("user:42", "42") is False


def test_actions_are_refused_when_the_role_does_not_match(tmp_path):
    class Adapter:
        def __init__(self):
            self.answer = {}

        async def answer_callback(self, callback_id, notification=None, message=None):
            self.answer = message or {}

    class Api:
        def __init__(self):
            self.calls = 0

        async def create_work_order(self, issue_id):
            self.calls += 1
            return {"id": "order-1"}

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    state.set_role("chat:77", "42", "resident")
    api, adapter = Api(), Adapter()
    # Assigning work is the УК action; a resident must not be able to do it.
    asyncio.run(
        handle_callback(
            adapter,
            api,
            IncomingMaxCallback("cb-4", "issue_assign:issue-1", "42", "77"),
            "https://example.test/app/",
            "dompuls_bot",
            state,
        )
    )
    assert api.calls == 0
    assert "Нужна роль" in adapter.answer["text"] or "роль" in adapter.answer["text"]


def test_verification_keeps_the_issue_watched(tmp_path):
    class Api:
        async def verify(self, issue_id, user_id, result):
            return {"id": issue_id, "title": "Лифт", "state": "DONE"}

    class Adapter:
        def __init__(self):
            self.answer = {}

        async def answer_callback(self, callback_id, notification=None, message=None):
            self.answer = message or {}

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    state.watchers = {"issue-1": {"chat:77": {"chat_id": "77", "user_id": "42", "last_state": "WORK_IN_PROGRESS"}}}
    asyncio.run(
        handle_callback(
            Adapter(),
            Api(),
            IncomingMaxCallback("cb-5", "verify_yes:issue-1", "42", "77"),
            "https://example.test/app/",
            "dompuls_bot",
            state,
        )
    )
    # The watcher moves to the state the API returned, so later changes are seen.
    assert state.watchers["issue-1"]["chat:77"]["last_state"] == "DONE"


def test_group_ack_says_nothing_for_chatter():
    assert group_ack({"result": "NO_ACTION"}) is None
    assert group_ack({}) is None
    assert "Принял, это уже было" in group_ack({"issue": {"id": "i", "title": "Лифт"}, "clustered": True})
    assert "Инициатива" in group_ack({"initiative": {"id": "n-1"}})
    assert "уточнение" in group_ack({"fallback": {"type": "ZONE_CLARIFICATION"}})
    assert "Проверю в личке" in group_ack({"fallback": {"type": "DUPLICATE_CONFIRMATION"}})


def test_group_ack_stays_short_for_a_long_title():
    ack = group_ack({"issue": {"id": "i", "title": "Домофон не открывается после обеда во всех подъездах жилого комплекса"}})
    assert len(ack) < 110
    assert ack.endswith("Подробности в личке.")


def test_group_ack_never_sent_in_a_private_chat(tmp_path):
    class Api:
        async def process_message(self, message, house_id, **kwargs):
            return {"issue": {"id": "issue-1", "title": "Лифт", "state": "NEEDS_CONFIRMATION"}}

    message = parse_incoming_message(
        {
            "update_type": "message_created",
            "message": {"sender": {"user_id": 42, "is_bot": False}, "body": {"mid": "m", "text": "лифт не работает"}},
        }
    )
    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    adapter = RecordingAdapter()
    asyncio.run(handle_message(adapter, Api(), state, message, "https://example.test/app/", "dompuls_bot"))
    assert len(adapter.sent) == 1
    assert adapter.sent[0]["user_id"] == "42"


def test_free_text_during_a_pending_question_reexplains_instead_of_losing_the_answer(tmp_path):
    class Api:
        async def process_message(self, message, house_id, **kwargs):
            return {"result": "NO_ACTION", "signal": {"id": "signal-2"}}

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    run_message(RecordingAdapter(), zone_clarification_api(), state, "лампочка сломалась")
    state.clear_dialog("user:42")
    state.begin_dialog("user:42", "report_zone", text="лампочка сломалась", author_id="42", zone_choices=[{"id": "zone-1", "name": "Первый подъезд"}])
    private = parse_incoming_message(
        {
            "update_type": "message_created",
            "message": {"sender": {"user_id": 42, "is_bot": False}, "body": {"mid": "dm-1", "text": "ну во втором подъезде наверное"}},
        }
    )
    adapter = RecordingAdapter()
    asyncio.run(handle_message(adapter, Api(), state, private, "https://example.test/app/", "dompuls_bot"))
    assert adapter.sent[0]["user_id"] == "42"
    assert "выбрать место" in adapter.sent[0]["text"]
    assert "лампочка сломалась" in adapter.sent[0]["text"]
    # The pending question is still answerable.
    assert state.dialog("user:42")["mode"] == "report_zone"


def test_chatter_in_the_group_does_not_restart_the_private_reminder(tmp_path):
    class Api:
        async def process_message(self, message, house_id, **kwargs):
            return {"result": "NO_ACTION", "signal": {"id": "signal-2"}}

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    run_message(RecordingAdapter(), zone_clarification_api(), state, "лампочка сломалась")
    assert run_message(RecordingAdapter(), Api(), state, "привет всем") == []
    assert state.dialog("user:42")["mode"] == "report_zone"


def test_a_new_report_replaces_an_unfinished_question_instead_of_being_blocked(tmp_path):
    class Api:
        async def process_message(self, message, house_id, **kwargs):
            return {"issue": {"id": "issue-9", "title": "Дверь: не закрывается", "state": "NEEDS_CONFIRMATION"}}

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    run_message(RecordingAdapter(), zone_clarification_api(), state, "лампочка сломалась")
    sent = run_message(RecordingAdapter(), Api(), state, "дверь в подъезде не закрывается")
    assert state.dialog("user:42") is None
    assert sent[0]["chat_id"] == "77"
    assert "Дверь" in sent[0]["text"]
    assert sent[1]["user_id"] == "42"
    assert "Проблема зарегистрирована" in sent[1]["text"]


def test_duplicate_question_names_the_existing_issue_and_offers_buttons():
    text = format_result(
        {
            "fallback": {
                "type": "DUPLICATE_CONFIRMATION",
                "score": 0.62,
                "candidate": {
                    "id": "issue-7",
                    "title": "Освещение: лампа в подъезде",
                    "category": "lighting",
                    "state": "NEEDS_CONFIRMATION",
                    "zone_id": "house-a-entrance-1",
                    "recurrence_count": 2,
                },
            }
        },
        "https://example.test/app/",
    )
    assert "Освещение: лампа в подъезде" in text
    assert "62%" in text
    assert "Уточните данные сообщения" not in text
    buttons = fallback_keyboard(
        {"signal": {"id": "signal-9"}, "fallback": {"type": "DUPLICATE_CONFIRMATION", "candidate": {"id": "issue-7"}}},
        "resident",
    )[0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "duplicate:signal-9:issue-7:LINK"
    assert buttons[0][1]["payload"] == "duplicate:signal-9:issue-7:CREATE_NEW"


def test_duplicate_callback_links_the_signal_to_the_existing_issue(tmp_path):
    class Api:
        def __init__(self):
            self.calls = []

        async def resolve_duplicate(self, signal_id, candidate_issue_id, decision, actor_id):
            self.calls.append((signal_id, candidate_issue_id, decision, actor_id))
            return {"id": "issue-7", "title": "Освещение", "state": "NEEDS_CONFIRMATION", "confirmations_count": 3}

    class Adapter:
        def __init__(self):
            self.answer = {}

        async def answer_callback(self, callback_id, notification=None, message=None):
            self.answer = message or {}

    state = PollState(str(tmp_path / "state.json"), "demo-house-a")
    api, adapter = Api(), Adapter()
    asyncio.run(
        handle_callback(
            adapter,
            api,
            IncomingMaxCallback("cb-2", "duplicate:signal-9:issue-7:LINK", "42", "77"),
            "https://example.test/app/",
            "dompuls_bot",
            state,
        )
    )
    assert api.calls == [("signal-9", "issue-7", "LINK", "42")]
    assert "объединено" in adapter.answer["text"]
    assert state.watchers["issue-7"]["chat:77"]["last_state"] == "NEEDS_CONFIRMATION"


def test_category_keyboard_covers_every_known_category():
    payloads = set()
    for row in category_keyboard()[0]["payload"]["buttons"]:
        for button in row:
            if button.get("payload", "").startswith("category:"):
                payloads.add(button["payload"])
    for category in CATEGORY_LABELS:
        assert f"category:{category}" in payloads, f"no button for {category}"
