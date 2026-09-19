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
        self.default_house_id = default_house_id
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
            self.marker = raw.get("marker")
            self.houses = raw.get("houses") or {}
            self.watchers = raw.get("watchers") or {}
            self.conversations = raw.get("conversations") or {}
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            self.marker = None
            self.houses = {}
            self.watchers = {}
            self.conversations = {}

    def house_for(self, message: IncomingMaxMessage) -> str:
        return self.houses.get(message.conversation_key, self.default_house_id)

    def set_house(self, message: IncomingMaxMessage, house_id: str) -> None:
        self.houses[message.conversation_key] = house_id
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

    async def process_message(self, message: IncomingMaxMessage, house_id: str) -> dict[str, Any]:
        result = await self.request(
            "POST",
            "/signals",
            json={
                "house_id": house_id,
                "text": message.text,
                "author_id": message.user_id,
                "chat_id": message.chat_id,
                "source_type": "max_message",
                "external_id": message.external_id,
                "attachments": message.attachments,
            },
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

    async def issue(self, issue_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/issues/{issue_id}")

    async def resident_confirm(self, issue_id: str, actor_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/issues/{issue_id}/resident-confirm", json={"actor_id": actor_id})

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


def inline_keyboard(buttons: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]


def issue_keyboard(issue: dict[str, Any], miniapp_url: str, bot_username: str) -> list[dict[str, Any]]:
    issue_id = str(issue["id"])
    rows: list[list[dict[str, Any]]] = []
    if issue.get("state") == "NEEDS_CONFIRMATION":
        rows.append([{"type": "callback", "text": "У меня тоже", "payload": f"confirm_issue:{issue_id}"}])
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
        "Команды: /status, /house_a, /house_b, /help"
    )


async def send_reply(adapter: MaxAdapter, message: IncomingMaxMessage, text: str, attachments: list[dict[str, Any]] | None = None) -> None:
    if message.chat_id:
        await adapter.send_message(text=text, chat_id=message.chat_id, attachments=attachments)
    else:
        await adapter.send_message(text=text, user_id=message.user_id, attachments=attachments)


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
        await send_reply(adapter, message, f"Дом переключён: `{house_id}`\n\nТеперь сообщения относятся к этому дому.")
        return
    house_id = state.house_for(message)
    if command in {"/start", "/help"}:
        await send_reply(adapter, message, help_text(house_id))
        return
    if command == "/status":
        status = await api.house_status(house_id)
        metrics = status["metrics"]
        house = status["house"]
        await send_reply(
            adapter,
            message,
            "**Состояние дома**\n"
            f"{house['address']}\n\n"
            f"Активные проблемы: {metrics['active_issues']}\n"
            f"В работе: {metrics['work_in_progress']}\n"
            f"Повторяющиеся: {metrics['recurring_issues']}\n"
            f"Инициативы: {metrics['initiatives']}",
        )
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
