import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .integrations.max_adapter import MaxAdapter, MaxAdapterError, build_max_adapter
from .integrations.max_updates import IncomingMaxCallback, IncomingMaxMessage, parse_incoming_callback, parse_incoming_message
from .settings import Settings, get_settings


LOGGER = logging.getLogger("dompuls.max_bot")
HOUSE_COMMANDS = {"/house_a": "demo-house-a", "/house_b": "demo-house-b"}


class PollState:
    def __init__(self, path: str, default_house_id: str):
        self.path = Path(path)
        self.marker: int | None = None
        self.houses: dict[str, str] = {}
        self.watchers: dict[str, dict[str, dict[str, str | None]]] = {}
        self.conversations: dict[str, dict[str, Any]] = {}
        self.dialogs: dict[str, dict[str, Any]] = {}
        self.default_house_id = default_house_id
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
            self.marker = raw.get("marker")
            self.houses = raw.get("houses") or {}
            self.watchers = raw.get("watchers") or {}
            self.conversations = raw.get("conversations") or {}
            self.dialogs = raw.get("dialogs") or {}
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            self.marker = None
            self.houses = {}
            self.watchers = {}
            self.conversations = {}
            self.dialogs = {}

    def house_for(self, message: IncomingMaxMessage) -> str:
        return self.houses.get(message.conversation_key, self.default_house_id)

    def house_for_key(self, conversation_key: str) -> str:
        return self.houses.get(conversation_key, self.default_house_id)

    def set_house(self, message: IncomingMaxMessage, house_id: str) -> None:
        self.houses[message.conversation_key] = house_id
        self.save()

    def set_house_key(self, conversation_key: str, house_id: str) -> None:
        self.houses[conversation_key] = house_id
        self.save()

    def begin_dialog(self, conversation_key: str, mode: str, **values: Any) -> None:
        self.dialogs[conversation_key] = {"mode": mode, **values}
        self.save()

    def dialog(self, conversation_key: str) -> dict[str, Any] | None:
        return self.dialogs.get(conversation_key)

    def clear_dialog(self, conversation_key: str) -> None:
        self.dialogs.pop(conversation_key, None)
        self.save()

    def set_marker(self, marker: int | None) -> None:
        self.marker = marker
        self.save()

    def remember_conversation(self, message: IncomingMaxMessage, permissions: dict[str, Any] | None = None) -> None:
        if not message.chat_id:
            return
        current = self.conversations.get(message.conversation_key, {})
        current.update(
            {
                "chat_id": message.chat_id,
                "house_id": self.house_for(message),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        if permissions is not None:
            current["permissions"] = permissions.get("permissions") or []
            current["has_read_all_messages"] = bool(permissions.get("has_read_all_messages"))
        self.conversations[message.conversation_key] = current
        self.save()

    def watch_issue(self, message: IncomingMaxMessage, issue: dict[str, Any]) -> None:
        self.watch_target(message.conversation_key, message.chat_id, message.user_id, issue)

    def watch_callback(self, callback: IncomingMaxCallback, issue: dict[str, Any]) -> None:
        self.watch_target(callback.conversation_key, callback.chat_id, callback.user_id, issue)

    def watch_target(
        self,
        conversation_key: str,
        chat_id: str | None,
        user_id: str,
        issue: dict[str, Any],
    ) -> None:
        issue_id = issue.get("id")
        if not issue_id:
            return
        self.watchers.setdefault(str(issue_id), {})[conversation_key] = {
            "chat_id": chat_id,
            "user_id": user_id,
            "last_state": issue.get("state"),
        }
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "marker": self.marker,
                    "houses": self.houses,
                    "watchers": self.watchers,
                    "conversations": self.conversations,
                    "dialogs": self.dialogs,
                },
                ensure_ascii=False,
            )
        )
        temporary.replace(self.path)


class DomPulsApi:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def request(self, method: str, path: str, **kwargs) -> Any:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=12.0) as client:
            response = await client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    async def process_message(
        self,
        message: IncomingMaxMessage,
        house_id: str,
        *,
        manual_category: str | None = None,
        manual_zone_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "house_id": house_id,
            "text": message.text,
            "author_id": message.user_id,
            "chat_id": message.chat_id,
            "source_type": "max_message",
            "external_id": message.external_id,
            "attachments": message.attachments,
        }
        if manual_category:
            body["manual_category"] = manual_category
        if manual_zone_id:
            body["manual_zone_id"] = manual_zone_id
        result = await self.request(
            "POST",
            "/signals",
            json=body,
        )
        issue = result.get("issue")
        if issue and issue.get("asset_id"):
            try:
                asset = await self.request("GET", f"/assets/{issue['asset_id']}")
                issue["asset_name"] = asset.get("name")
            except httpx.HTTPError:
                LOGGER.warning("Could not enrich issue %s with asset name", issue.get("id"))
        return result

    async def house_status(self, house_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/houses/{house_id}/state")

    async def create_initiative(self, house_id: str, title: str, summary: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            "/initiatives",
            json={
                "house_id": house_id,
                "title": title[:220],
                "summary": summary[:2000],
                "options": ["Поддерживаю", "Нужно обсудить место", "Не поддерживаю"],
                "requires_formal_process": True,
            },
        )

    async def submit(self, issue_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/issues/{issue_id}/submit", json={})

    async def accept(self, issue_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/issues/{issue_id}/accept", json={})

    async def create_work_order(self, issue_id: str) -> dict[str, Any]:
        return await self.request("POST", "/work-orders", json={"issue_id": issue_id})

    async def update_work_order(self, order_id: str, status: str) -> dict[str, Any]:
        return await self.request("PATCH", f"/work-orders/{order_id}", json={"status": status})

    async def add_evidence(self, order_id: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/work-orders/{order_id}/evidence",
            json={
                "type": "after_photo",
                "uri": "/demo/elevator-after.svg",
                "comment": "Контрольный запуск выполнен, evidence добавлен через MAX.",
            },
        )

    async def issue(self, issue_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/issues/{issue_id}")

    async def resident_confirm(self, issue_id: str, actor_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/issues/{issue_id}/resident-confirm", json={"actor_id": actor_id})

    async def confirm(self, issue_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/issues/{issue_id}/confirm", json={})

    async def verify(self, issue_id: str, actor_id: str, result: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/issues/{issue_id}/verify",
            json={"verifier_type": "resident", "verifier_id": actor_id, "result": result},
        )

    async def initiative(self, initiative_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/initiatives/{initiative_id}")

    async def vote(self, initiative_id: str, voter_id: str, option: str) -> dict[str, Any]:
        return await self.request("POST", f"/initiatives/{initiative_id}/poll", json={"voter_id": voter_id, "option": option})

    async def handoff(self, initiative_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/initiatives/{initiative_id}/handoff", json={})


def inline_keyboard(buttons: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]


def menu_keyboard() -> list[dict[str, Any]]:
    return inline_keyboard(
        [
            [
                {"type": "callback", "text": "Сообщить о проблеме", "payload": "menu:report"},
                {"type": "callback", "text": "Состояние дома", "payload": "menu:status"},
            ],
            [
                {"type": "callback", "text": "Предложить инициативу", "payload": "menu:initiative"},
                {"type": "callback", "text": "Сменить дом", "payload": "menu:houses"},
            ],
        ]
    )


def cancel_keyboard() -> list[dict[str, Any]]:
    return inline_keyboard([[{"type": "callback", "text": "Отмена", "payload": "menu:cancel"}]])


def category_keyboard() -> list[dict[str, Any]]:
    return inline_keyboard(
        [
            [
                {"type": "callback", "text": "Лифт", "payload": "category:elevator"},
                {"type": "callback", "text": "Освещение", "payload": "category:lighting"},
            ],
            [
                {"type": "callback", "text": "Вода / отопление", "payload": "category:water"},
                {"type": "callback", "text": "Дверь / домофон", "payload": "category:door"},
            ],
            [{"type": "callback", "text": "Другое", "payload": "category:other"}],
        ]
    )


def zone_keyboard(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buttons = [
        {"type": "callback", "text": str(zone.get("name") or zone.get("number") or "Зона"), "payload": f"zone:{zone['id']}"}
        for zone in zones[:8]
    ]
    return inline_keyboard([buttons[index : index + 2] for index in range(0, len(buttons), 2)] + [[{"type": "callback", "text": "Отмена", "payload": "menu:cancel"}]])


def house_keyboard() -> list[dict[str, Any]]:
    return inline_keyboard(
        [
            [{"type": "callback", "text": "Дом A · Никольский 12", "payload": "house:demo-house-a"}],
            [{"type": "callback", "text": "Дом B · Центральная 7", "payload": "house:demo-house-b"}],
        ]
    )


def status_keyboard(status: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    for issue in status.get("issues") or []:
        if issue.get("state") in {"CLOSED", "CANCELLED", "REJECTED", "DUPLICATE"}:
            continue
        rows.append([{"type": "callback", "text": f"Проблема: {issue.get('title', 'без названия')}"[:128], "payload": f"open_issue:{issue['id']}"}])
    for initiative in status.get("initiatives") or []:
        rows.append([{"type": "callback", "text": f"Инициатива: {initiative.get('title', 'без названия')}"[:128], "payload": f"open_initiative:{initiative['id']}"}])
    rows.append([{"type": "callback", "text": "Сообщить о проблеме", "payload": "menu:report"}])
    return inline_keyboard(rows)


def issue_keyboard(issue: dict[str, Any], miniapp_url: str, bot_username: str) -> list[dict[str, Any]]:
    issue_id = str(issue["id"])
    rows: list[list[dict[str, Any]]] = []
    if issue.get("state") == "NEEDS_CONFIRMATION":
        rows.append(
            [
                {"type": "callback", "text": "У меня тоже", "payload": f"confirm_issue:{issue_id}"},
                {"type": "callback", "text": "Подтвердить и передать", "payload": f"issue_confirm:{issue_id}"},
            ]
        )
    if issue.get("state") == "ACTION_READY":
        rows.append([{"type": "callback", "text": "Передать в УК", "payload": f"issue_submit:{issue_id}"}])
    if issue.get("state") == "SUBMITTED":
        rows.append([{"type": "callback", "text": "Принять в работу", "payload": f"issue_accept:{issue_id}"}])
    order = (issue.get("work_orders") or [])[-1:]
    current_order = order[0] if order else None
    if issue.get("state") == "ACCEPTED" and not current_order:
        rows.append([{"type": "callback", "text": "Назначить исполнителя", "payload": f"issue_assign:{issue_id}"}])
    if current_order and current_order.get("status") == "ASSIGNED":
        rows.append([{"type": "callback", "text": "Начать работу", "payload": f"order_start:{issue_id}"}])
    if current_order and current_order.get("status") == "IN_PROGRESS":
        if current_order.get("evidence"):
            rows.append([{"type": "callback", "text": "Завершить работу", "payload": f"order_done:{issue_id}"}])
        else:
            rows.append([{"type": "callback", "text": "Добавить фото evidence", "payload": f"order_evidence:{issue_id}"}])
    if issue.get("state") == "DONE_PENDING_VERIFICATION":
        rows.append(
            [
                {"type": "callback", "text": "Исправлено", "payload": f"verify_yes:{issue_id}"},
                {"type": "callback", "text": "Не исправлено", "payload": f"verify_no:{issue_id}"},
            ]
        )
    rows.append([{"type": "open_app", "text": "Открыть карточку", "web_app": bot_username, "payload": f"issue_{issue_id}"}])
    if miniapp_url and "localhost" not in miniapp_url:
        rows.append([{"type": "link", "text": "Открыть в браузере", "url": f"{miniapp_url.rstrip('/')}?issue={issue_id}"}])
    return inline_keyboard(rows)


def initiative_keyboard(initiative: dict[str, Any], bot_username: str) -> list[dict[str, Any]]:
    rows = [
        [{"type": "callback", "text": option[:128], "payload": f"vote:{initiative['id']}:{index}"}]
        for index, option in enumerate(initiative.get("options") or [])
    ]
    if initiative.get("state") == "INFORMAL_POLL":
        rows.append([{"type": "callback", "text": "Завершить опрос и передать", "payload": f"initiative_handoff:{initiative['id']}"}])
    rows.append([{"type": "open_app", "text": "Открыть инициативу", "web_app": bot_username, "payload": f"initiative_{initiative['id']}"}])
    return inline_keyboard(rows)


def format_initiative(initiative: dict[str, Any]) -> str:
    votes = initiative.get("votes") or {}
    options = "\n".join(f"• {option} — {votes.get(option, 0)}" for option in initiative.get("options", []))
    return (
        "**Инициатива жителей**\n"
        f"{initiative.get('title')}\n\n"
        f"{initiative.get('summary')}\n\n"
        f"Неформальный опрос:\n{options}\n\n"
        "Это обсуждение жителей, не юридически значимое ОСС."
    )


def format_status(status: dict[str, Any]) -> str:
    house = status.get("house") or {}
    metrics = status.get("metrics") or {}
    active = [
        item
        for item in status.get("issues") or []
        if item.get("state") not in {"CLOSED", "CANCELLED", "REJECTED", "DUPLICATE"}
    ]
    issue_lines = "\n".join(f"• {item.get('title')} — {item.get('state')}" for item in active[:5]) or "• Активных проблем нет"
    return (
        "**Состояние дома**\n"
        f"{house.get('address', 'Дом')}\n\n"
        f"Активных проблем: {metrics.get('active_issues', 0)}\n"
        f"В работе: {metrics.get('work_in_progress', 0)}\n"
        f"Повторяющихся: {metrics.get('recurring_issues', 0)}\n"
        f"Инициатив: {metrics.get('initiatives', 0)}\n\n"
        f"Что требует внимания:\n{issue_lines}"
    )


def format_result(result: dict[str, Any], miniapp_url: str) -> str:
    if fallback := result.get("fallback"):
        choices = fallback.get("choices") or []
        choice_text = "\n".join(f"• {item.get('name')}" for item in choices[:6])
        suffix = f"\n\nВарианты:\n{choice_text}" if choice_text else ""
        return f"Нужно уточнение\n\n{fallback.get('message', 'Уточните данные сообщения.')}{suffix}"
    if issue := result.get("issue"):
        clustered = bool(result.get("clustered"))
        heading = "Сообщение связано с существующей проблемой" if clustered else "Проблема зарегистрирована"
        asset = issue.get("asset_name") or issue.get("asset_id") or "место уточняется"
        lines = [
            f"**{heading}**",
            f"{issue.get('title', 'Проблема дома')}",
            f"Объект: {asset}",
            f"Статус: {issue.get('state')}",
            f"Подтверждений: {issue.get('confirmations_count', 0)}",
        ]
        recurrence = issue.get("recurrence_count", 0)
        if recurrence:
            lines.append(f"Повторяемость: {recurrence} событий в истории")
        lines.append("Спасибо — обновления будут отражаться в состоянии дома.")
        if miniapp_url and "localhost" not in miniapp_url:
            lines.append(f"[Открыть ДомПульс]({miniapp_url})")
        return "\n".join(lines)
    if initiative := result.get("initiative"):
        return format_initiative(initiative)
    if result.get("result") == "NO_ACTION":
        return "Я не увидел обращения по дому. Опишите проблему или инициативу чуть подробнее."
    return "Сообщение принято и сохранено."


def help_text(house_id: str) -> str:
    return (
        "**ДомПульс — бот состояния дома**\n\n"
        "Опишите проблему обычным сообщением, например:\n"
        "«лифт опять встал во втором подъезде»\n\n"
        "Или инициативу:\n"
        "«на парковке нужен второй фонарь»\n\n"
        f"Текущий дом: `{house_id}`\n"
        "Команды: /status, /house_a, /house_b, /menu, /help"
    )


async def send_reply(adapter: MaxAdapter, message: IncomingMaxMessage, text: str, attachments: list[dict[str, Any]] | None = None) -> None:
    if message.chat_id:
        await adapter.send_message(text=text, chat_id=message.chat_id, attachments=attachments)
    else:
        await adapter.send_message(text=text, user_id=message.user_id, attachments=attachments)


def callback_message(callback: IncomingMaxCallback, text: str, attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"text": text, "format": "markdown", "attachments": attachments or []}


async def handle_message(
    adapter: MaxAdapter,
    api: DomPulsApi,
    state: PollState,
    message: IncomingMaxMessage,
    miniapp_url: str,
    bot_username: str,
) -> None:
    if message.chat_id:
        known = state.conversations.get(message.conversation_key)
        permissions = None
        if not known or "has_read_all_messages" not in known:
            try:
                permissions = await adapter.check_chat_permissions(message.chat_id)
                LOGGER.info(
                    "Registered MAX group chat %s; read_all_messages=%s",
                    message.chat_id,
                    permissions.get("has_read_all_messages"),
                )
            except MaxAdapterError as exc:
                LOGGER.warning("Could not check permissions for chat %s: %s", message.chat_id, exc)
        state.remember_conversation(message, permissions)
    command = message.text.split(maxsplit=1)[0].lower()
    if command in HOUSE_COMMANDS:
        house_id = HOUSE_COMMANDS[command]
        state.set_house(message, house_id)
        await send_reply(adapter, message, f"Дом переключён: `{house_id}`\n\nТеперь сообщения относятся к этому дому.", menu_keyboard())
        return
    house_id = state.house_for(message)
    if command in {"/start", "/help", "/menu"}:
        await send_reply(adapter, message, help_text(house_id), menu_keyboard())
        return
    if command == "/cancel":
        state.clear_dialog(message.conversation_key)
        await send_reply(adapter, message, "Диалог отменён. Выберите действие:", menu_keyboard())
        return
    dialog = state.dialog(message.conversation_key)
    if dialog and dialog.get("mode") == "report_text":
        state.begin_dialog(
            message.conversation_key,
            "report_category",
            text=message.text,
            author_id=message.user_id,
            chat_id=message.chat_id,
            external_id=message.external_id,
            attachments=message.attachments,
        )
        await send_reply(adapter, message, "Что случилось? Выберите категорию — это поможет точнее привязать сигнал к объекту дома.", category_keyboard())
        return
    if dialog and dialog.get("mode") == "initiative_text":
        initiative = await api.create_initiative(house_id, "Инициатива жителей", message.text)
        state.clear_dialog(message.conversation_key)
        await send_reply(adapter, message, format_initiative(initiative), initiative_keyboard(initiative, bot_username))
        return
    if command == "/status":
        status = await api.house_status(house_id)
        await send_reply(adapter, message, format_status(status), status_keyboard(status))
        return
    result = await api.process_message(message, house_id)
    attachments = None
    if issue := result.get("issue"):
        state.watch_issue(message, issue)
        attachments = issue_keyboard(issue, miniapp_url, bot_username)
    elif initiative := result.get("initiative"):
        attachments = initiative_keyboard(initiative, bot_username)
    await send_reply(adapter, message, format_result(result, miniapp_url), attachments)


async def handle_callback(
    adapter: MaxAdapter,
    api: DomPulsApi,
    callback: IncomingMaxCallback,
    miniapp_url: str,
    bot_username: str,
    state: PollState | None = None,
) -> None:
    action, separator, value = callback.payload.partition(":")
    if not separator:
        await adapter.answer_callback(callback.callback_id, notification="Неизвестное действие")
        return
    conversation_key = callback.conversation_key
    if action == "menu":
        if value == "report":
            state and state.begin_dialog(conversation_key, "report_text")
            await adapter.answer_callback(
                callback.callback_id,
                notification="Опишите проблему одним сообщением",
                message=callback_message(callback, "**Сообщить о проблеме**\n\nНапишите, что случилось. Следующим шагом я предложу категорию и место.\n\nМожно отменить: `/cancel`", cancel_keyboard()),
            )
            return
        if value == "initiative":
            state and state.begin_dialog(conversation_key, "initiative_text")
            await adapter.answer_callback(
                callback.callback_id,
                notification="Напишите предложение",
                message=callback_message(callback, "**Новая инициатива**\n\nОпишите предложение жителей одним сообщением. Я соберу его в инициативу и запущу неофициальный опрос.", cancel_keyboard()),
            )
            return
        if value == "houses":
            await adapter.answer_callback(callback.callback_id, notification="Выберите дом", message=callback_message(callback, "**Выберите дом для этого чата**", house_keyboard()))
            return
        if value in {"status", "issues"}:
            house_id = state.house_for_key(conversation_key) if state else "demo-house-a"
            status = await api.house_status(house_id)
            await adapter.answer_callback(callback.callback_id, notification="Состояние обновлено", message=callback_message(callback, format_status(status), status_keyboard(status)))
            return
        if value == "help":
            house_id = state.house_for_key(conversation_key) if state else "demo-house-a"
            await adapter.answer_callback(callback.callback_id, notification="Подсказка", message=callback_message(callback, help_text(house_id), menu_keyboard()))
            return
        if value == "cancel":
            state and state.clear_dialog(conversation_key)
            await adapter.answer_callback(callback.callback_id, notification="Диалог отменён", message=callback_message(callback, "Выберите следующее действие:", menu_keyboard()))
            return
    if action == "house":
        if state:
            state.set_house_key(conversation_key, value)
        await adapter.answer_callback(callback.callback_id, notification=f"Выбран {value}", message=callback_message(callback, f"Дом переключён: `{value}`\n\nТеперь сообщения в этом чате относятся к выбранной конфигурации.", menu_keyboard()))
        return
    if action == "category":
        if not state or not state.dialog(conversation_key) or state.dialog(conversation_key).get("mode") != "report_category":
            await adapter.answer_callback(callback.callback_id, notification="Начните с кнопки «Сообщить о проблеме»")
            return
        dialog = {key: item for key, item in state.dialog(conversation_key).items() if key != "mode"}
        state.begin_dialog(conversation_key, "report_zone", **dialog, category=value)
        house_id = state.house_for_key(conversation_key)
        status = await api.house_status(house_id)
        zones: dict[str, dict[str, str]] = {}
        for asset in status.get("assets", []):
            zone_id = str(asset.get("zone_id") or "")
            if zone_id:
                zones.setdefault(zone_id, {"id": zone_id, "name": zone_id.replace("house-", "").replace("-", " ")})
        await adapter.answer_callback(callback.callback_id, notification="Теперь выберите место", message=callback_message(callback, "**Где это произошло?**", zone_keyboard(list(zones.values()))))
        return
    if action == "zone":
        dialog = state.dialog(conversation_key) if state else None
        if not state or not dialog or dialog.get("mode") != "report_zone":
            await adapter.answer_callback(callback.callback_id, notification="Диалог устарел. Начните заново.")
            return
        message = IncomingMaxMessage(
            text=str(dialog["text"]),
            user_id=str(dialog["author_id"]),
            chat_id=dialog.get("chat_id"),
            external_id=str(dialog["external_id"]),
            attachments=dialog.get("attachments") or [],
        )
        result = await api.process_message(message, state.house_for_key(conversation_key), manual_category=str(dialog["category"]), manual_zone_id=value)
        state.clear_dialog(conversation_key)
        issue = result.get("issue")
        if issue:
            state.watch_issue(message, issue)
        attachments = issue_keyboard(issue, miniapp_url, bot_username) if issue else menu_keyboard()
        await adapter.answer_callback(callback.callback_id, notification="Сигнал обработан", message=callback_message(callback, format_result(result, miniapp_url), attachments))
        return
    if action == "open_issue":
        issue = await api.issue(value)
        if state:
            state.watch_callback(callback, issue)
        await adapter.answer_callback(callback.callback_id, notification="Карточка проблемы", message=callback_message(callback, format_result({"issue": issue}, miniapp_url), issue_keyboard(issue, miniapp_url, bot_username)))
        return
    if action == "open_initiative":
        initiative = await api.initiative(value)
        await adapter.answer_callback(callback.callback_id, notification="Инициатива", message=callback_message(callback, format_initiative(initiative), initiative_keyboard(initiative, bot_username)))
        return
    if action == "confirm_issue":
        result = await api.resident_confirm(value, callback.user_id)
        issue = result["issue"]
        if state:
            state.watch_callback(callback, issue)
        notification = "Вы уже подтверждали эту проблему" if result.get("idempotent_replay") else "Подтверждение учтено"
        await adapter.answer_callback(
            callback.callback_id,
            notification=notification,
            message={"text": format_result({"issue": issue, "clustered": True}, miniapp_url), "format": "markdown", "attachments": issue_keyboard(issue, miniapp_url, bot_username)},
        )
        return
    if action == "issue_confirm":
        issue = await api.confirm(value)
        if state:
            state.watch_callback(callback, issue)
        await adapter.answer_callback(callback.callback_id, notification="Подтверждено. Следующий шаг — передать в УК.", message=callback_message(callback, format_result({"issue": issue}, miniapp_url), issue_keyboard(issue, miniapp_url, bot_username)))
        return
    if action in {"issue_submit", "issue_accept", "issue_assign", "order_start", "order_evidence", "order_done"}:
        issue_id = value
        if action == "issue_submit":
            issue = await api.submit(issue_id)
        elif action == "issue_accept":
            issue = await api.accept(issue_id)
        elif action == "issue_assign":
            await api.create_work_order(issue_id)
            issue = await api.issue(issue_id)
        else:
            issue = await api.issue(issue_id)
            order = (issue.get("work_orders") or [])[-1:]
            if not order:
                await adapter.answer_callback(callback.callback_id, notification="Для проблемы ещё не назначена работа")
                return
            order_id = order[0]["id"]
            if action == "order_start":
                await api.update_work_order(order_id, "IN_PROGRESS")
            elif action == "order_evidence":
                await api.add_evidence(order_id)
            else:
                await api.update_work_order(order_id, "DONE")
            issue = await api.issue(issue_id)
        if state:
            state.watch_callback(callback, issue)
        await adapter.answer_callback(callback.callback_id, notification="Статус обновлён", message=callback_message(callback, format_result({"issue": issue}, miniapp_url), issue_keyboard(issue, miniapp_url, bot_username)))
        return
    if action == "initiative_handoff":
        initiative = await api.handoff(value)
        await adapter.answer_callback(callback.callback_id, notification="Результат опроса сохранён", message=callback_message(callback, format_initiative(initiative), initiative_keyboard(initiative, bot_username)))
        return
    if action == "vote":
        initiative_id, option_separator, option_index = value.rpartition(":")
        if not option_separator or not option_index.isdigit():
            await adapter.answer_callback(callback.callback_id, notification="Некорректный вариант")
            return
        initiative = await api.initiative(initiative_id)
        options = initiative.get("options") or []
        index = int(option_index)
        if index >= len(options):
            await adapter.answer_callback(callback.callback_id, notification="Вариант больше недоступен")
            return
        updated = await api.vote(initiative_id, callback.user_id, options[index])
        await adapter.answer_callback(
            callback.callback_id,
            notification="Голос учтён",
            message={"text": format_initiative(updated), "format": "markdown", "attachments": initiative_keyboard(updated, bot_username)},
        )
        return
    if action in {"verify_yes", "verify_no"}:
        result = "confirmed" if action == "verify_yes" else "rejected"
        issue = await api.verify(value, callback.user_id, result)
        notification = "Спасибо, результат подтверждён" if result == "confirmed" else "Проблема переоткрыта"
        await adapter.answer_callback(
            callback.callback_id,
            notification=notification,
            message={"text": format_result({"issue": issue}, miniapp_url), "format": "markdown", "attachments": issue_keyboard(issue, miniapp_url, bot_username)},
        )
        return
    await adapter.answer_callback(callback.callback_id, notification="Неизвестное действие")


async def notify_state_changes(
    adapter: MaxAdapter,
    api: DomPulsApi,
    state: PollState,
    miniapp_url: str,
    bot_username: str,
) -> None:
    changed = False
    for issue_id, conversations in list(state.watchers.items()):
        try:
            issue = await api.issue(issue_id)
        except httpx.HTTPError:
            continue
        current_state = str(issue.get("state"))
        for watcher in conversations.values():
            previous_state = watcher.get("last_state")
            if previous_state == current_state:
                continue
            if previous_state:
                text = f"**Статус проблемы изменился**\n{issue.get('title')}\n{previous_state} → {current_state}"
                await adapter.send_message(
                    text=text,
                    chat_id=watcher.get("chat_id"),
                    user_id=None if watcher.get("chat_id") else watcher.get("user_id"),
                    attachments=issue_keyboard(issue, miniapp_url, bot_username),
                )
            watcher["last_state"] = current_state
            changed = True
    if changed:
        state.save()


async def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if settings.max_mode != "real":
        LOGGER.warning("MAX bot worker is idle because MAX_MODE=%s", settings.max_mode)
        while True:
            await asyncio.sleep(3600)
    adapter = build_max_adapter(settings)
    bot = await adapter.get_bot()
    subscriptions = await adapter.get_subscriptions()
    if subscriptions:
        raise MaxAdapterError("Long polling is unavailable while a MAX webhook subscription exists")
    bot_username = str(bot.get("username") or "")
    LOGGER.info("Connected to MAX as @%s (%s)", bot_username or "unknown", bot.get("user_id", "unknown"))
    state = PollState(settings.max_poll_state_path, settings.max_default_house_id)
    api = DomPulsApi(settings.dompuls_api_url)
    failures = 0
    while True:
        try:
            page = await adapter.get_updates(
                marker=state.marker,
                timeout=settings.max_poll_timeout,
                update_types=["message_created", "message_callback", "bot_started"],
            )
            for update in page.get("updates") or []:
                callback = parse_incoming_callback(update)
                if callback:
                    try:
                        await handle_callback(adapter, api, callback, settings.max_miniapp_url, bot_username, state)
                    except httpx.HTTPStatusError as exc:
                        detail = "Действие уже выполнено или больше недоступно"
                        try:
                            detail = exc.response.json().get("detail") or detail
                        except (ValueError, AttributeError):
                            pass
                        await adapter.answer_callback(callback.callback_id, notification=detail[:200])
                    continue
                message = parse_incoming_message(update)
                if message and not message.sender_is_bot:
                    await handle_message(adapter, api, state, message, settings.max_miniapp_url, bot_username)
            if page.get("marker") is not None:
                state.set_marker(page["marker"])
            await notify_state_changes(adapter, api, state, settings.max_miniapp_url, bot_username)
            failures = 0
        except (MaxAdapterError, httpx.HTTPError, OSError, KeyError) as exc:
            failures += 1
            delay = min(30, 2 ** min(failures, 5))
            LOGGER.exception("MAX polling iteration failed; retrying in %ss: %s", delay, exc)
            await asyncio.sleep(delay)


if __name__ == "__main__":
    asyncio.run(run())
