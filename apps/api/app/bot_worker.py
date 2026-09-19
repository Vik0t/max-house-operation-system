import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from .integrations.max_adapter import MaxAdapter, MaxAdapterError, build_max_adapter
from .integrations.max_updates import IncomingMaxMessage, parse_incoming_message
from .settings import Settings, get_settings


LOGGER = logging.getLogger("dompuls.max_bot")
HOUSE_COMMANDS = {"/house_a": "demo-house-a", "/house_b": "demo-house-b"}


class PollState:
    def __init__(self, path: str, default_house_id: str):
        self.path = Path(path)
        self.marker: int | None = None
        self.houses: dict[str, str] = {}
        self.default_house_id = default_house_id
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
            self.marker = raw.get("marker")
            self.houses = raw.get("houses") or {}
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            self.marker = None
            self.houses = {}

    def house_for(self, message: IncomingMaxMessage) -> str:
        return self.houses.get(message.conversation_key, self.default_house_id)

    def set_house(self, message: IncomingMaxMessage, house_id: str) -> None:
        self.houses[message.conversation_key] = house_id
        self.save()

    def set_marker(self, marker: int | None) -> None:
        self.marker = marker
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"marker": self.marker, "houses": self.houses}, ensure_ascii=False))
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
        options = "\n".join(f"• {option}" for option in initiative.get("options", []))
        return (
            "**Инициатива создана**\n"
            f"{initiative.get('title')}\n\n"
            f"{initiative.get('summary')}\n\n"
            f"Неформальный опрос:\n{options}\n\n"
            "Это обсуждение жителей, не юридически значимое ОСС."
        )
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


async def send_reply(adapter: MaxAdapter, message: IncomingMaxMessage, text: str) -> None:
    if message.chat_id:
        await adapter.send_message(text=text, chat_id=message.chat_id)
    else:
        await adapter.send_message(text=text, user_id=message.user_id)


async def handle_message(
    adapter: MaxAdapter,
    api: DomPulsApi,
    state: PollState,
    message: IncomingMaxMessage,
    miniapp_url: str,
) -> None:
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
    await send_reply(adapter, message, format_result(result, miniapp_url))


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
    LOGGER.info("Connected to MAX as @%s (%s)", bot.get("username", "unknown"), bot.get("user_id", "unknown"))
    state = PollState(settings.max_poll_state_path, settings.max_default_house_id)
    api = DomPulsApi(settings.dompuls_api_url)
    failures = 0
    while True:
        try:
            page = await adapter.get_updates(
                marker=state.marker,
                timeout=settings.max_poll_timeout,
                update_types=["message_created", "bot_started"],
            )
            for update in page.get("updates") or []:
                message = parse_incoming_message(update)
                if message and not message.sender_is_bot:
                    await handle_message(adapter, api, state, message, settings.max_miniapp_url)
            if page.get("marker") is not None:
                state.set_marker(page["marker"])
            failures = 0
        except (MaxAdapterError, httpx.HTTPError, OSError, KeyError) as exc:
            failures += 1
            delay = min(30, 2 ** min(failures, 5))
            LOGGER.exception("MAX polling iteration failed; retrying in %ss: %s", delay, exc)
            await asyncio.sleep(delay)


if __name__ == "__main__":
    asyncio.run(run())
