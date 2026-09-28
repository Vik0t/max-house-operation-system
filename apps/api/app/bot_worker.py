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
HOUSE_COMMANDS = {
    "/house_a": "demo-house-a",
    "/house_b": "demo-house-b",
    "/дом_a": "demo-house-a",
    "/дом_b": "demo-house-b",
}
HOUSE_LABELS = {
    "demo-house-a": "Дом А · Никольский, 12",
    "demo-house-b": "Дом Б · Центральная, 7",
}
ROLE_LABELS = {
    "resident": "Житель",
    "representative": "Домоуправляющий",
    "uk": "УК / диспетчер",
    "executor": "Исполнитель",
}
STATE_LABELS = {
    "DETECTED": "Обнаружена",
    "NEEDS_CONFIRMATION": "Ждёт подтверждений",
    "CONFIRMED": "Подтверждена",
    "ACTION_READY": "Готова к передаче",
    "SUBMITTED": "Передана в управляющую компанию",
    "ACCEPTED": "Принята в работу",
    "WORK_IN_PROGRESS": "В работе",
    "DONE_PENDING_VERIFICATION": "Ждёт проверки жителем",
    "VERIFIED": "Результат подтверждён",
    "CLOSED": "Закрыта",
    "REOPENED": "Переоткрыта",
    "DUPLICATE": "Объединена с другой проблемой",
    "REJECTED": "Отклонена",
    "CANCELLED": "Отменена",
}
ORDER_STATE_LABELS = {
    "NEW": "Новая",
    "ASSIGNED": "Назначена исполнителю",
    "IN_PROGRESS": "Исполняется",
    "DONE": "Выполнена, ждёт проверки",
    "ACCEPTED": "Принята жителем",
    "REWORK_REQUIRED": "Нужна доработка",
}
INITIATIVE_STATE_LABELS = {
    "DETECTED": "Обнаружена",
    "DRAFT": "Черновик",
    "DISCUSSION": "Обсуждение",
    "INFORMAL_POLL": "Опрос жителей",
    "RESULT": "Результат опроса",
    "CLOSED": "Закрыта",
    "FORMAL_HANDOFF_REQUIRED": "Нужна официальная передача",
}
CATEGORY_LABELS = {
    "elevator": "Лифт",
    "lighting": "Освещение",
    "water": "Вода и отопление",
    "door": "Дверь и домофон",
    "parking": "Парковка",
    "other": "Другое",
}
PROVENANCE_LABELS = {
    "OFFICIAL": "официальный источник",
    "USER": "сообщение жителя",
    "CALCULATED": "расчёт системы",
    "AI_INFERENCE": "вывод ИИ, требует проверки",
    "SYNTHETIC": "демонстрационные данные",
}


def state_label(value: str | None, labels: dict[str, str] = STATE_LABELS) -> str:
    return labels.get(str(value), "Состояние уточняется")


def house_label(house_id: str) -> str:
    return HOUSE_LABELS.get(house_id, house_id)


def category_label(value: str | None) -> str:
    raw = str(value or "").strip()
    return CATEGORY_LABELS.get(raw.lower(), raw or "Другое")


def provenance_label(value: str | None) -> str:
    return PROVENANCE_LABELS.get(str(value or ""), "источник уточняется")


def humanize_asset_name(value: str | None) -> str:
    """Keep internal/config names out of user-facing MAX messages."""

    raw = str(value or "").strip()
    if not raw:
        return "Объект уточняется"
    replacements = {
        "lighting": "Освещение",
        "parking light": "Освещение парковки",
        "house-a-lighting-2": "Освещение подъезда 2",
    }
    lowered = raw.lower()
    if lowered in replacements:
        return replacements[lowered]
    if lowered.startswith("lighting"):
        return "Освещение" + raw[len("lighting"):]
    return raw


def localized_issue_title(issue: dict[str, Any]) -> str:
    title = str(issue.get("title") or "Проблема дома").strip()
    if ":" not in title:
        return humanize_asset_name(title)
    prefix, suffix = title.split(":", 1)
    if str(issue.get("category") or "").lower() in {"lighting", "water", "door"} and "лифт" in prefix.lower():
        prefix = localized_asset_label(issue)
    return f"{humanize_asset_name(prefix)}:{suffix}"


def localized_asset_label(issue: dict[str, Any]) -> str:
    asset = humanize_asset_name(issue.get("asset_name"))
    category = str(issue.get("category") or "").lower()
    # Older demo messages can contain a wrong asset hint (for example a
    # lighting report attached to an elevator). Never show an impossible
    # combination to a resident; preserve the issue for audit but use the
    # category as the visible fallback until it is manually resolved.
    if category == "lighting" and (asset == "Объект уточняется" or "лифт" in asset.lower() or asset.lower() == "lighting"):
        return "Освещение"
    if category == "elevator" and asset.lower().startswith("lighting"):
        return "Лифт"
    return asset


def nav_row(*buttons: dict[str, Any]) -> list[list[dict[str, Any]]]:
    return [[*buttons]]


def back_button(payload: str = "back:menu", text: str = "Назад") -> dict[str, Any]:
    return {"type": "callback", "text": text, "payload": payload}


def menu_button() -> dict[str, Any]:
    return back_button("back:menu", "В меню")


class PollState:
    def __init__(self, path: str, default_house_id: str):
        self.path = Path(path)
        self.marker: int | None = None
        self.houses: dict[str, str] = {}
        self.watchers: dict[str, dict[str, dict[str, str | None]]] = {}
        self.conversations: dict[str, dict[str, Any]] = {}
        self.dialogs: dict[str, dict[str, Any]] = {}
        # Roles are deliberately scoped to a conversation: a group chat can
        # contain a resident, a representative and a contractor at the same
        # time without exposing operator controls to everybody, and a role
        # picked in a private chat never leaks into the house group.
        self.roles: dict[str, dict[str, str]] = {}
        # signal_id -> chat the duplicate question was asked from, so the house
        # chat can be told about the decision made in a private chat.
        self.duplicate_chats: dict[str, str] = {}
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
            self.roles = raw.get("roles") or {}
            self.duplicate_chats = raw.get("duplicate_chats") or {}
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            self.marker = None
            self.houses = {}
            self.watchers = {}
            self.conversations = {}
            self.dialogs = {}
            self.roles = {}
            self.duplicate_chats = {}

    def remember_duplicate_chat(self, signal_id: str, chat_id: str | None) -> None:
        if not signal_id or not chat_id:
            return
        self.duplicate_chats[signal_id] = chat_id
        self.save()

    def pop_duplicate_chat(self, signal_id: str) -> str | None:
        chat_id = self.duplicate_chats.pop(signal_id, None)
        if chat_id:
            self.save()
        return chat_id

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

    def role_for(self, conversation_key: str, user_id: str) -> str:
        # Roles are per conversation: a role picked in a private chat must not
        # leak into the house group (and vice versa), otherwise choosing
        # "УК" once would silently grant operator buttons everywhere.
        role = (self.roles.get(conversation_key) or {}).get(str(user_id), "resident")
        return role if role in ROLE_LABELS else "resident"

    def has_role(self, conversation_key: str, user_id: str) -> bool:
        return str(user_id) in (self.roles.get(conversation_key) or {})

    def set_role(self, conversation_key: str, user_id: str, role: str) -> None:
        if role not in ROLE_LABELS:
            role = "resident"
        user_id = str(user_id)
        self.roles.setdefault(conversation_key, {})[user_id] = role
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
                    "roles": self.roles,
                    "duplicate_chats": self.duplicate_chats,
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

    async def resolve_signal(self, signal_id: str, category: str, zone_id: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/signals/{signal_id}/resolve",
            json={"category": category, "zone_id": zone_id},
        )

    async def resolve_duplicate(self, signal_id: str, candidate_issue_id: str, decision: str, actor_id: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/signals/{signal_id}/resolve-duplicate",
            json={"candidate_issue_id": candidate_issue_id, "decision": decision, "actor_id": actor_id},
        )

    async def house_status(self, house_id: str, viewer_id: str | None = None, role: str = "resident") -> dict[str, Any]:
        params = {"role": role}
        if viewer_id:
            params["viewer_id"] = viewer_id
        return await self.request("GET", f"/houses/{house_id}/state", params=params)

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

    async def select_route(self, issue_id: str, destination: str) -> dict[str, Any]:
        return await self.request("POST", f"/issues/{issue_id}/route", json={"destination": destination})

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


def menu_keyboard(role: str = "resident") -> list[dict[str, Any]]:
    """Role-specific home menu; the bot should feel like a different product per role."""
    primary = {
        "resident": [
            [{"type": "callback", "text": "Сообщить о проблеме", "payload": "menu:report"}],
            [{"type": "callback", "text": "Мои обращения", "payload": "menu:issues"}, {"type": "callback", "text": "Проверить результат", "payload": "menu:queue"}],
        ],
        "representative": [
            [{"type": "callback", "text": "Требуют моего решения", "payload": "menu:queue"}],
            [{"type": "callback", "text": "Повторяющиеся проблемы", "payload": "menu:status"}, {"type": "callback", "text": "Инициативы", "payload": "menu:initiatives"}],
        ],
        "uk": [
            [{"type": "callback", "text": "Новые обращения", "payload": "menu:queue"}],
            [{"type": "callback", "text": "В работе", "payload": "menu:status"}, {"type": "callback", "text": "Ждут проверки", "payload": "menu:verify"}],
        ],
        "executor": [
            [{"type": "callback", "text": "Мои работы", "payload": "menu:queue"}],
            [{"type": "callback", "text": "Завершённые работы", "payload": "menu:status"}],
        ],
    }.get(role, [])
    common = [
        [{"type": "callback", "text": "Состояние дома", "payload": "menu:status"}, {"type": "callback", "text": "Сменить дом", "payload": "menu:houses"}],
        [{"type": "callback", "text": "Помощь", "payload": "menu:help"}, {"type": "callback", "text": "Моя рабочая роль", "payload": "menu:role"}],
    ]
    if role in {"resident", "representative"}:
        common.insert(1, [{"type": "callback", "text": "Инициативы жителей", "payload": "menu:initiatives"}])
    if role == "resident":
        common.insert(2, [{"type": "callback", "text": "Предложить инициативу", "payload": "menu:initiative"}])
    return inline_keyboard(primary + common)


def cancel_keyboard() -> list[dict[str, Any]]:
    return inline_keyboard([[menu_button()]])


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
            [
                {"type": "callback", "text": "Парковка", "payload": "category:parking"},
                {"type": "callback", "text": "Другое", "payload": "category:other"},
            ],
            [menu_button()],
        ]
    )


def zone_keyboard(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buttons = [
        {"type": "callback", "text": str(zone.get("name") or zone.get("number") or "Зона"), "payload": f"zone:{zone['id']}"}
        for zone in zones[:8]
    ]
    return inline_keyboard(
        [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
        + [[back_button("back:category", "Назад к категории")], [{"type": "callback", "text": "Отменить обращение", "payload": "menu:cancel"}]]
    )


def duplicate_keyboard(signal_id: str, candidate_issue_id: str) -> list[dict[str, Any]]:
    return inline_keyboard(
        [
            [
                {"type": "callback", "text": "Это та же проблема", "payload": f"duplicate:{signal_id}:{candidate_issue_id}:LINK"},
                {"type": "callback", "text": "Другая проблема", "payload": f"duplicate:{signal_id}:{candidate_issue_id}:CREATE_NEW"},
            ],
            [menu_button()],
        ]
    )


def fallback_keyboard(result: dict[str, Any], role: str) -> list[dict[str, Any]]:
    """Buttons that let the resident act on a clarification the API asked for.

    Zone and category clarifications already get their own keyboards at the call
    site. The duplicate question had none, which is why it looked like a dead end.
    """
    fallback = result.get("fallback") or {}
    if fallback.get("type") == "DUPLICATE_CONFIRMATION":
        signal_id = str((result.get("signal") or {}).get("id") or "")
        candidate_id = str((fallback.get("candidate") or {}).get("id") or "")
        if signal_id and candidate_id:
            return duplicate_keyboard(signal_id, candidate_id)
    return menu_keyboard(role)


def house_keyboard() -> list[dict[str, Any]]:
    return inline_keyboard(
        [
            [{"type": "callback", "text": "Дом А · Никольский, 12", "payload": "house:demo-house-a"}],
            [{"type": "callback", "text": "Дом Б · Центральная, 7", "payload": "house:demo-house-b"}],
            [menu_button()],
        ]
    )


def role_keyboard() -> list[dict[str, Any]]:
    return inline_keyboard(
        [
            [
                {"type": "callback", "text": "Я житель", "payload": "role:resident"},
                {"type": "callback", "text": "Я домоуправляющий", "payload": "role:representative"},
            ],
            [
                {"type": "callback", "text": "Я УК / диспетчер", "payload": "role:uk"},
                {"type": "callback", "text": "Я исполнитель", "payload": "role:executor"},
            ],
            [menu_button()],
        ]
    )


def issue_button_label(issue: dict[str, Any]) -> str:
    asset = localized_asset_label(issue)
    if asset == "Объект уточняется":
        title = str(issue.get("title") or "Проблема дома")
        asset = humanize_asset_name(title.split(":", 1)[0])
    state = state_label(issue.get("state"))
    confirmations = int(issue.get("confirmations_count") or 0)
    related = int(issue.get("related_issue_count") or 1)
    suffix = f" · {confirmations} подтвержд." if confirmations else ""
    if related > 1:
        suffix += f" · {related} сообщения объединены"
    return f"{asset} · {state}{suffix}"[:128]


def status_keyboard(status: dict[str, Any], role: str = "resident", queue_only: bool = False) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    active = [
        issue
        for issue in status.get("issues") or []
        if issue.get("state") not in {"CLOSED", "CANCELLED", "REJECTED", "DUPLICATE"}
    ]
    attention_states = ROLE_ATTENTION_STATES.get(role, ROLE_ATTENTION_STATES["resident"])
    if queue_only:
        active = [issue for issue in active if issue.get("state") in attention_states]
    active.sort(key=lambda item: (item.get("state") not in attention_states, item.get("last_seen_at") or ""))
    for issue in active:
        rows.append([{"type": "callback", "text": issue_button_label(issue), "payload": f"open_issue:{issue['id']}"}])
    initiatives = status.get("initiatives") or []
    if initiatives:
        rows.append([{"type": "callback", "text": f"Инициативы жителей · {len(initiatives)}", "payload": "menu:initiatives"}])
        for initiative in initiatives[:5]:
            rows.append([{"type": "callback", "text": f"Инициатива · {initiative.get('title', 'без названия')}"[:128], "payload": f"open_initiative:{initiative['id']}"}])
    if not queue_only and role in {"resident", "representative"}:
        rows.append([{"type": "callback", "text": "Сообщить о проблеме", "payload": "menu:report"}])
    rows.append([menu_button()])
    return inline_keyboard(rows)


def notification_keyboard(issue: dict[str, Any]) -> list[dict[str, Any]]:
    return inline_keyboard(
        [
            [{"type": "callback", "text": "Открыть обращение", "payload": f"open_issue:{issue['id']}"}],
            [menu_button()],
        ]
    )


def destination_label(destination: str | None) -> str:
    value = (destination or "").lower()
    if "uk-" in value or "management" in value or "управ" in value:
        return "управляющей компании"
    if "representative" in value or "представ" in value:
        return "домоуправляющему"
    if value:
        return "ответственному"
    return "адресату"


def issue_action(issue: dict[str, Any]) -> dict[str, Any] | None:
    actions = issue.get("actions") or []
    return actions[-1] if actions else None


def issue_route_text(issue: dict[str, Any]) -> str | None:
    action = issue_action(issue)
    if not action:
        return None
    destination = destination_label(action.get("suggested_destination"))
    confidence = float(action.get("confidence") or 0)
    prefix = "Предлагаемый адресат" if confidence < 0.7 else "Адресат"
    text = f"{prefix}: {destination}"
    rationale = str(action.get("rationale") or "").strip()
    if rationale:
        text += f"\nПочему: {rationale}"
    return text


def route_keyboard(issue_id: str) -> list[dict[str, Any]]:
    return inline_keyboard(
        [
            [{"type": "callback", "text": "Передать в управляющую компанию", "payload": f"route_select:{issue_id}:management_org"}],
            [{"type": "callback", "text": "Оставить домоуправляющему", "payload": f"route_select:{issue_id}:representative"}],
            [menu_button()],
        ]
    )


def asset_label(issue: dict[str, Any]) -> str:
    if issue.get("asset_name"):
        return localized_asset_label(issue)
    title = str(issue.get("title") or "")
    if ":" in title:
        return humanize_asset_name(title.split(":", 1)[0])
    asset_id = str(issue.get("asset_id") or "")
    if "elevator" in asset_id:
        suffix = asset_id.rsplit("-", 1)[-1]
        return f"Лифт №{suffix}" if suffix.isdigit() else "Лифт"
    if "lighting" in asset_id:
        return "Освещение"
    return "Объект уточняется"


def issue_keyboard(
    issue: dict[str, Any],
    miniapp_url: str,
    bot_username: str,
    role: str = "legacy",
) -> list[dict[str, Any]]:
    issue_id = str(issue["id"])
    rows: list[list[dict[str, Any]]] = []
    # ``legacy`` keeps the helper backwards-compatible for API consumers and
    # tests. The real MAX bot always passes a concrete role, so a resident can
    # never see operator buttons in a group chat.
    if role in {"resident", "legacy"} and issue.get("state") == "NEEDS_CONFIRMATION":
        rows.append(
            [
                {"type": "callback", "text": "У меня тоже", "payload": f"confirm_issue:{issue_id}"},
            ]
        )
    if role in {"representative", "legacy"} and issue.get("state") == "NEEDS_CONFIRMATION":
        rows.append([{"type": "callback", "text": "Подтвердить проблему", "payload": f"issue_confirm:{issue_id}"}])
    if role in {"representative", "legacy"} and issue.get("state") == "ACTION_READY":
        action = issue_action(issue)
        confidence = float((action or {}).get("confidence") or 1)
        if confidence < 0.7:
            rows.append([{"type": "callback", "text": "Выбрать адресата", "payload": f"route:{issue_id}"}])
        else:
            destination = destination_label((action or {}).get("suggested_destination"))
            rows.append([{"type": "callback", "text": f"Передать {destination}", "payload": f"issue_submit:{issue_id}"}])
    if role in {"uk", "legacy"} and issue.get("state") == "SUBMITTED":
        rows.append([{"type": "callback", "text": "Принять в работу", "payload": f"issue_accept:{issue_id}"}])
    order = (issue.get("work_orders") or [])[-1:]
    current_order = order[0] if order else None
    if role in {"uk", "legacy"} and issue.get("state") == "ACCEPTED" and not current_order:
        rows.append([{"type": "callback", "text": "Назначить исполнителя", "payload": f"issue_assign:{issue_id}"}])
    if role in {"executor", "legacy"} and current_order and current_order.get("status") == "ASSIGNED":
        rows.append([{"type": "callback", "text": "Начать работу", "payload": f"order_start:{issue_id}"}])
    if role in {"executor", "legacy"} and current_order and current_order.get("status") == "IN_PROGRESS":
        if current_order.get("evidence"):
            rows.append([{"type": "callback", "text": "Завершить работу", "payload": f"order_done:{issue_id}"}])
        else:
            # The API has no photo upload from MAX yet; add_evidence records a
            # demo evidence entry. The label must not promise a photo upload.
            rows.append([{"type": "callback", "text": "Зафиксировать выполнение", "payload": f"order_evidence:{issue_id}"}])
    if role in {"resident", "legacy"} and issue.get("state") == "DONE_PENDING_VERIFICATION":
        rows.append(
            [
                {"type": "callback", "text": "Исправлено", "payload": f"verify_yes:{issue_id}"},
                {"type": "callback", "text": "Не исправлено", "payload": f"verify_no:{issue_id}"},
            ]
        )
    rows.append([{"type": "open_app", "text": "Открыть карточку", "web_app": bot_username, "payload": f"issue_{issue_id}"}])
    rows.append([menu_button()])
    return inline_keyboard(rows)


def initiative_keyboard(initiative: dict[str, Any], bot_username: str, role: str = "legacy") -> list[dict[str, Any]]:
    rows = [
        [{"type": "callback", "text": option[:128], "payload": f"vote:{initiative['id']}:{index}"}]
        for index, option in enumerate(initiative.get("options") or [])
    ]
    if initiative.get("state") == "INFORMAL_POLL" and role in {"representative", "legacy"}:
        rows.append([{"type": "callback", "text": "Зафиксировать результат", "payload": f"initiative_handoff:{initiative['id']}"}])
    rows.append([{"type": "open_app", "text": "Открыть инициативу", "web_app": bot_username, "payload": f"initiative_{initiative['id']}"}])
    rows.append([menu_button()])
    return inline_keyboard(rows)


def format_initiative(initiative: dict[str, Any]) -> str:
    votes = initiative.get("votes") or {}
    options = "\n".join(f"• {option} — {votes.get(option, 0)}" for option in initiative.get("options", []))
    return (
        "**Инициатива жителей**\n"
        f"{initiative.get('title')}\n\n"
        f"{initiative.get('summary')}\n\n"
        f"Состояние: {state_label(initiative.get('state'), INITIATIVE_STATE_LABELS)}\n\n"
        f"Опрос жителей:\n{options}\n\n"
        "Это обсуждение жителей, не юридически значимое общее собрание собственников."
    )


def issue_next_step(issue: dict[str, Any]) -> str:
    state = issue.get("state")
    if state == "NEEDS_CONFIRMATION":
        return "Следующий шаг: жители подтверждают сигнал, домоуправляющий решает, передавать ли его в УК."
    if state == "ACTION_READY":
        action = issue_action(issue)
        destination = destination_label((action or {}).get("suggested_destination"))
        return f"Следующий шаг: домоуправляющий передаёт проблему {destination}."
    if state == "SUBMITTED":
        return "Следующий шаг: УК принимает обращение в работу."
    if state == "ACCEPTED":
        order = (issue.get("work_orders") or [])[-1:]
        if order and order[0].get("status") == "ASSIGNED":
            return "Следующий шаг: исполнитель начинает работу."
        return "Следующий шаг: УК назначает исполнителя."
    if state == "WORK_IN_PROGRESS":
        order = (issue.get("work_orders") or [])[-1:]
        if order and not order[0].get("evidence"):
            return "Следующий шаг: исполнитель фиксирует выполнение (демо-запись без загрузки фото)."
        return "Следующий шаг: исполнитель завершает работу."
    if state == "DONE_PENDING_VERIFICATION":
        return "Следующий шаг: житель проверяет результат — исправлено или нужно переоткрыть."
    if state == "CLOSED":
        return "Проблема закрыта, результат записан в историю объекта."
    return "Обновления будут отражаться в состоянии дома."


STATUS_SECTIONS = (
    ("NEEDS_CONFIRMATION", "Требуют подтверждений"),
    ("ACTION_READY", "Требуют решения домоуправляющего"),
    ("CONFIRMED", "Подтверждены и готовятся к передаче"),
    ("SUBMITTED", "Переданы в управляющую компанию"),
    ("ACCEPTED", "Приняты управляющей компанией"),
    ("WORK_IN_PROGRESS", "В работе"),
    ("DONE_PENDING_VERIFICATION", "Ждут проверки жителем"),
    ("REOPENED", "Переоткрыты"),
    ("DETECTED", "Требуют уточнения"),
)
ROLE_ATTENTION_STATES = {
    "resident": {"NEEDS_CONFIRMATION", "DONE_PENDING_VERIFICATION", "REOPENED"},
    "representative": {"NEEDS_CONFIRMATION", "CONFIRMED", "ACTION_READY", "REOPENED"},
    "uk": {"SUBMITTED", "ACCEPTED", "WORK_IN_PROGRESS", "DONE_PENDING_VERIFICATION"},
    "executor": {"ACCEPTED", "WORK_IN_PROGRESS"},
}


def format_status(status: dict[str, Any], role: str = "resident", heading: str = "Состояние дома") -> str:
    house = status.get("house") or {}
    metrics = status.get("metrics") or {}
    active = [
        item
        for item in status.get("issues") or []
        if item.get("state") not in {"CLOSED", "CANCELLED", "REJECTED", "DUPLICATE"}
    ]
    attention_states = ROLE_ATTENTION_STATES.get(role, ROLE_ATTENTION_STATES["resident"])
    active.sort(key=lambda item: (item.get("state") not in attention_states, item.get("last_seen_at") or ""))
    sections: list[str] = []
    for state, heading in STATUS_SECTIONS:
        items = [item for item in active if item.get("state") == state]
        if not items:
            continue
        lines = "\n".join(f"• {issue_button_label(item)}" for item in items[:5])
        sections.append(f"**{heading} ({len(items)})**\n{lines}")
    if not sections:
        sections.append("**Открытых проблем нет**\nДом сейчас не требует внимания.")

    role_hint = {
        "resident": "Ваши действия: подтвердить знакомую проблему или проверить завершённую работу.",
        "representative": "Ваши действия: домоуправляющий проверяет подтверждения и принимает решение о передаче в УК.",
        "uk": "Ваши действия: принять обращение, назначить работу и обновлять её состояние.",
        "executor": "Ваши действия: открыть назначенную работу, зафиксировать выполнение и завершить её.",
    }.get(role, "Откройте проблему, чтобы увидеть доступное действие.")
    return (
        f"**{heading}**\n"
        f"{house.get('address', 'Дом')}\n\n"
        f"Открытых проблем: {metrics.get('active_issues', 0)}\n"
        f"В работе: {metrics.get('work_in_progress', 0)}\n"
        f"Ждут подтверждений: {metrics.get('awaiting_confirmation', 0)}\n"
        f"Ждут проверки: {metrics.get('awaiting_verification', 0)}\n"
        f"Повторяющихся: {metrics.get('recurring_issues', 0)}\n"
        f"Инициатив жителей: {metrics.get('initiatives', 0)}\n\n"
        f"{role_hint}\n\n"
        + "\n\n".join(sections)
    )


def format_fallback(fallback: dict[str, Any], miniapp_url: str) -> str:
    """Ask the resident a question the API could not answer on its own.

    Every branch names what the bot is confused about. The duplicate branch used
    to fall through to a bare "Уточните данные сообщения", which in a group gave
    no way to tell which message or which existing problem was meant.
    """
    kind = fallback.get("type")
    if kind == "DUPLICATE_CONFIRMATION":
        candidate = fallback.get("candidate") or {}
        lines = [
            "**Похоже, такая проблема уже есть**",
            localized_issue_title(candidate),
            f"Объект: {asset_label(candidate)}",
            f"Статус: {state_label(candidate.get('state'))}",
            f"Совпадение по смыслу: {round(float(fallback.get('score') or 0) * 100)}%",
        ]
        if recurrence := candidate.get("recurrence_count", 0):
            lines.append(f"Повторяемость: {recurrence} событий в истории")
        lines.append("")
        lines.append("Это та же проблема или другая? Если другая — добавьте деталь, например подъезд или этаж.")
        return "\n".join(lines)
    choices = fallback.get("choices") or []
    choice_text = "\n".join(f"• {item.get('name')}" for item in choices[:6])
    heading = "**Нужно уточнить место**" if kind == "ZONE_CLARIFICATION" else "**Нужно уточнение**"
    body = fallback.get("message") or "Уточните данные сообщения."
    suffix = f"\n\nВарианты:\n{choice_text}" if choice_text else ""
    return f"{heading}\n\n{body}{suffix}"


def format_result(result: dict[str, Any], miniapp_url: str) -> str:
    if fallback := result.get("fallback"):
        return format_fallback(fallback, miniapp_url)
    if issue := result.get("issue"):
        clustered = bool(result.get("clustered"))
        heading = "Сообщение связано с существующей проблемой" if clustered else "Проблема зарегистрирована"
        asset = asset_label(issue)
        lines = [
            f"**{heading}**",
            localized_issue_title(issue),
            f"Объект: {asset}",
            f"Статус: {state_label(issue.get('state'))}",
            f"Подтверждений: {issue.get('confirmations_count', 0)}",
            f"Источник: {provenance_label(issue.get('provenance'))}",
        ]
        if issue.get("signals_count"):
            lines.append(f"Сообщений объединено: {issue['signals_count']}")
        recurrence = issue.get("recurrence_count", 0)
        if recurrence:
            lines.append(f"Повторяемость: {recurrence} событий в истории")
        if route := issue_route_text(issue):
            lines.append(route)
        lines.append(issue_next_step(issue))
        return "\n".join(lines)
    if initiative := result.get("initiative"):
        return format_initiative(initiative)
    if result.get("result") == "NO_ACTION":
        return "Я не увидел обращения по дому. Опишите проблему или инициативу чуть подробнее."
    return "Сообщение принято и сохранено."


def is_recognized_result(result: dict[str, Any]) -> bool:
    """Whether a processed message is worth answering at all.

    The pipeline answers NO_ACTION for ordinary chatter that carries no house
    signal. A group chat contains greetings, questions about the weather and
    conversations between residents, so replying to every one of them would fill
    the house chat with bot noise. Those messages are stored but not announced.
    """
    if result.get("issue") or result.get("initiative") or result.get("fallback"):
        return True
    return (result.get("result") or "").upper() not in {"", "NO_ACTION"}


def help_text(house_id: str, role: str = "resident") -> str:
    return (
        "**ДомПульс — бот состояния дома**\n\n"
        "Опишите проблему обычным сообщением, например:\n"
        "«лифт опять встал во втором подъезде»\n\n"
        "Или инициативу:\n"
        "«на парковке нужен второй фонарь»\n\n"
        f"Текущий дом: {house_label(house_id)}\n"
        f"{role_text(role)}\n\n"
        "Команды: /состояние, /меню, /назад, /отмена, /помощь\n"
        "В демо дом можно сменить кнопкой «Сменить дом» или командами /дом_a и /дом_b. Смена действует на весь чат.\n"
        "Действия разделены по ролям: житель → домоуправляющий → УК → исполнитель."
    )


def short_issue_title(issue: dict[str, Any], limit: int = 60) -> str:
    title = " ".join(localized_issue_title(issue).split())
    return title if len(title) <= limit else title[: limit - 1] + "…"


def group_ack(result: dict[str, Any]) -> str | None:
    """The single line a house chat gets for a recognised message.

    A shared chat should show that something was taken in, not the whole card:
    every resident sees the line, only the author gets the details in a private
    chat. Returns None when the message was not a house matter, so the bot keeps
    quiet instead of acknowledging small talk.
    """
    if issue := result.get("issue"):
        verb = "Принял, это уже было" if result.get("clustered") else "Записал"
        return f"✅ {verb}: {short_issue_title(issue)}. Подробности в личке."
    if result.get("initiative"):
        return "✅ Инициатива создана. Опрос в личке."
    fallback = result.get("fallback") or {}
    kind = fallback.get("type")
    if kind in {"ZONE_CLARIFICATION", "MANUAL_CLASSIFICATION"}:
        return "⏳ Записал, но нужно уточнение. Спрошу в личке."
    if kind == "DUPLICATE_CONFIRMATION":
        return "❓ Похоже, такая уже есть. Проверю в личке."
    return None


async def send_reply(adapter: MaxAdapter, message: IncomingMaxMessage, text: str, attachments: list[dict[str, Any]] | None = None, *, private: bool = False, ack: str | None = None) -> None:
    """Answer a group message.

    ``private`` sends the reply to the sender instead of the chat. ``ack`` is the
    one-line summary posted in the house chat alongside it, so neighbours see that
    a report was taken in while the card, the buttons and the questions stay with
    the person who needs them. A resident who never opened the bot private chat
    cannot be written to, so the reply falls back to the chat.
    """
    if message.chat_id and not private:
        await adapter.send_message(text=text, chat_id=message.chat_id, attachments=attachments)
        return
    if message.chat_id and ack:
        await adapter.send_message(text=ack, chat_id=message.chat_id)
    try:
        await adapter.send_message(text=text, user_id=message.user_id, attachments=attachments)
    except MaxAdapterError:
        if not message.chat_id:
            raise
        LOGGER.warning("Direct message to user %s failed; answering in chat %s instead", message.user_id, message.chat_id)
        await adapter.send_message(text=f"{text}\n\n_Не смог открыть личный чат, поэтому показываю здесь._", chat_id=message.chat_id, attachments=attachments)


def callback_message(callback: IncomingMaxCallback, text: str, attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"text": text, "format": "markdown", "attachments": attachments or []}


def dialog_key(chat_id: str | None, user_id: str | None) -> str:
    """State a pending clarification belongs to.

    A house group is shared, so a clarification stored against the chat could be
    answered by any resident: one person's "where?" would be closed by somebody
    else's button press. Binding the dialog to its author also makes it possible
    to ask privately, because the buttons then arrive from the private chat,
    where the same key is used.
    """
    return f"user:{user_id}" if user_id else f"chat:{chat_id}"


def clarification_text(question: str, original: str) -> str:
    """A question about one specific message, with that message quoted back.

    A group holds a dozen messages a minute. Without the quote the resident has no
    way to tell which line the bot meant, which is what made the old bare
    "Уточните данные сообщения" unreadable.
    """
    quoted = " ".join((original or "").split())
    if not quoted:
        return question
    if len(quoted) > 140:
        quoted = quoted[:137] + "…"
    return f"{question}\n\nПро сообщение: «{quoted}»"


def current_role(state: PollState | None, conversation_key: str, user_id: str) -> str:
    return state.role_for(conversation_key, user_id) if state else "resident"


def role_text(role: str) -> str:
    return f"Текущая роль: **{ROLE_LABELS.get(role, ROLE_LABELS['resident'])}**"


def role_denied_text(required: str) -> str:
    return (
        f"Это действие доступно роли «{ROLE_LABELS[required]}».\n\n"
        "В ДомПульсе житель сообщает и подтверждает, домоуправляющий принимает решение о передаче, "
        "а УК и исполнитель обрабатывают работу. Выберите свою рабочую роль в меню, если это демо-сценарий."
    )


async def open_clarification(
    adapter: MaxAdapter,
    state: PollState,
    message: IncomingMaxMessage,
    result: dict[str, Any],
    pending: str,
) -> bool:
    """Ask the author for what the pipeline could not work out.

    The question goes to the author privately, quoting their own words, and the
    pending state is keyed by person so the buttons returning from the private
    chat find the right dialog. Returns False when the result needs no follow-up.
    """
    fallback = result.get("fallback") or {}
    if not fallback or fallback.get("type") == "DUPLICATE_CONFIRMATION":
        return False
    classification = result.get("classification") or {}
    dialog_values = {
        "text": message.text,
        "author_id": message.user_id,
        "chat_id": message.chat_id,
        "external_id": message.external_id,
        "attachments": message.attachments,
        "signal_id": (result.get("signal") or {}).get("id"),
    }
    if fallback.get("type") == "ZONE_CLARIFICATION" and classification.get("category"):
        state.begin_dialog(pending, "report_zone", **dialog_values, category=str(classification["category"]), zone_choices=fallback.get("choices") or [])
        choices = fallback.get("choices") or []
        await send_reply(adapter, message, clarification_text("Я понял категорию. Уточните только место проблемы:", message.text), zone_keyboard(choices), private=True, ack=group_ack(result))
        return True
    state.begin_dialog(pending, "report_category", **dialog_values)
    await send_reply(adapter, message, clarification_text("Уточните только категорию — место я определю по истории дома.", message.text), category_keyboard(), private=True, ack=group_ack(result))
    return True


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
    pending = dialog_key(message.chat_id, message.user_id)
    if command in HOUSE_COMMANDS:
        house_id = HOUSE_COMMANDS[command]
        state.set_house(message, house_id)
        await send_reply(adapter, message, f"Дом переключён: {house_label(house_id)}\n\nТеперь сообщения в этом чате относятся к этому дому. Смена действует для всех участников чата.", menu_keyboard(current_role(state, message.conversation_key, message.user_id)), private=True)
        return
    house_id = state.house_for(message)
    if command in {"/start", "/help", "/menu", "/помощь", "/меню"}:
        role = current_role(state, message.conversation_key, message.user_id)
        if command == "/start" and not state.has_role(message.conversation_key, message.user_id):
            await send_reply(
                adapter,
                message,
                help_text(house_id, role) + "\n\nДля демо выберите рабочую роль — от неё зависят доступные действия. Роль выбирается отдельно для каждого чата.",
                role_keyboard(),
                private=True,
            )
        else:
            await send_reply(adapter, message, help_text(house_id, role), menu_keyboard(role), private=True)
        return
    if command in {"/back", "/назад"}:
        dialog = state.dialog(pending)
        if dialog and dialog.get("mode") == "report_zone":
            preserved = {key: item for key, item in dialog.items() if key not in {"mode", "category"}}
            state.begin_dialog(pending, "report_category", **preserved)
            await send_reply(adapter, message, "Вернулись к выбору категории:", category_keyboard(), private=True)
        else:
            state.clear_dialog(pending)
            await send_reply(adapter, message, "Главное меню:", menu_keyboard(current_role(state, message.conversation_key, message.user_id)), private=True)
        return
    if command in {"/cancel", "/отмена"}:
        state.clear_dialog(pending)
        await send_reply(adapter, message, "Диалог отменён. Выберите действие:", menu_keyboard(current_role(state, message.conversation_key, message.user_id)), private=True)
        return
    dialog = state.dialog(pending)
    if dialog and dialog.get("mode") == "report_text":
        # First try the complete message. Clarification is only shown when the
        # structured pipeline really lacks context; a clear message such as
        # “лифт во втором подъезде” goes straight to an Issue.
        result = await api.process_message(message, house_id)
        if result.get("issue") or result.get("initiative") or result.get("result") == "NO_ACTION" or result.get("fallback"):
            state.clear_dialog(pending)
            await announce_result(adapter, state, message, result, miniapp_url, bot_username, pending)
            return
        role = current_role(state, message.conversation_key, message.user_id)
        await send_reply(adapter, message, format_result(result, miniapp_url), fallback_keyboard(result, role), private=True, ack=group_ack(result))
        return
    if dialog and dialog.get("mode") == "initiative_text":
        initiative = await api.create_initiative(house_id, "Инициатива жителей", message.text)
        state.clear_dialog(pending)
        await send_reply(
            adapter,
            message,
            format_initiative(initiative),
            initiative_keyboard(initiative, bot_username, current_role(state, message.conversation_key, message.user_id)),
            private=True,
            ack="✅ Инициатива создана. Опрос в личке." if message.chat_id else None,
        )
        return
    if dialog and dialog.get("mode") in {"report_zone", "report_category"}:
        # A new report matters more than finishing the old question, so try it
        # first: if it is understood it replaces the pending question, otherwise
        # the buttons are offered again. Free text used to be treated as a new
        # report and silently lost the answer to the pending one.
        fresh = await api.process_message(message, house_id)
        if is_recognized_result(fresh):
            state.clear_dialog(pending)
            await announce_result(adapter, state, message, fresh, miniapp_url, bot_username, pending)
            return
        if message.chat_id:
            # Chatter in the house chat must not restart the reminder for a
            # question only its author can see.
            return
        if dialog["mode"] == "report_zone":
            question, keyboard = "Осталось выбрать место — нажмите кнопку ниже.", zone_keyboard(dialog.get("zone_choices") or [])
        else:
            question, keyboard = "Осталось выбрать категорию — нажмите кнопку ниже.", category_keyboard()
        await send_reply(adapter, message, clarification_text(question, str(dialog.get("text") or "")), keyboard, private=True)
        return
    if command in {"/status", "/состояние"}:
        status = await api.house_status(house_id)
        role = current_role(state, message.conversation_key, message.user_id)
        await send_reply(adapter, message, format_status(status, role), status_keyboard(status, role), private=True)
        return
    result = await api.process_message(message, house_id)
    await announce_result(adapter, state, message, result, miniapp_url, bot_username, pending)


async def announce_result(
    adapter: MaxAdapter,
    state: PollState,
    message: IncomingMaxMessage,
    result: dict[str, Any],
    miniapp_url: str,
    bot_username: str,
    pending: str,
) -> None:
    """Turn a processed message into what the house chat and the author see.

    The chat gets one line when the message was a house matter and nothing at all
    otherwise; the author always gets the card, the buttons and any question.
    """
    if await open_clarification(adapter, state, message, result, pending):
        return
    if message.chat_id and not is_recognized_result(result):
        LOGGER.info("Kept quiet about unrecognised message %s in chat %s", message.external_id, message.chat_id)
        return
    role = current_role(state, message.conversation_key, message.user_id)
    attachments = None
    if issue := result.get("issue"):
        state.watch_issue(message, issue)
        attachments = issue_keyboard(issue, miniapp_url, bot_username, role)
    elif initiative := result.get("initiative"):
        attachments = initiative_keyboard(initiative, bot_username, role)
    if (result.get("fallback") or {}).get("type") == "DUPLICATE_CONFIRMATION":
        state.remember_duplicate_chat(str((result.get("signal") or {}).get("id") or ""), message.chat_id)
    await send_reply(adapter, message, format_result(result, miniapp_url), attachments or fallback_keyboard(result, role), private=True, ack=group_ack(result))


async def resolve_duplicate(
    adapter: MaxAdapter,
    api: DomPulsApi,
    callback: IncomingMaxCallback,
    signal_id: str,
    candidate_issue_id: str,
    decision: str,
    miniapp_url: str,
    bot_username: str,
    state: PollState | None = None,
) -> None:
    """Answer the "is this the same problem?" question the API asked.

    Until this existed the bot printed an unexplained clarification and stopped,
    leaving the signal attached to nothing.
    """
    role = current_role(state, callback.conversation_key, callback.user_id)
    if decision not in {"LINK", "CREATE_NEW"}:
        await adapter.answer_callback(callback.callback_id, notification="Не удалось распознать решение")
        return
    try:
        issue = await api.resolve_duplicate(signal_id, candidate_issue_id, decision, callback.user_id)
    except Exception:
        LOGGER.exception("Could not resolve duplicate %s as %s", signal_id, decision)
        await adapter.answer_callback(callback.callback_id, notification="Не удалось сохранить решение")
        return
    if state:
        state.watch_callback(callback, issue)
    if decision == "LINK":
        text = f"**Спасибо, сообщение объединено**\n\n{localized_issue_title(issue)}\n\nТеперь у этой проблемы на одно подтверждение больше."
    else:
        text = f"**Создана отдельная проблема**\n\n{format_result({'issue': issue}, miniapp_url)}"
    # The buttons sit in a private chat, so the house chat is told separately.
    if state and (chat_id := state.pop_duplicate_chat(signal_id)):
        await adapter.send_message(text=group_ack({"issue": issue, "clustered": decision == "LINK"}) or "", chat_id=chat_id)
    await adapter.answer_callback(
        callback.callback_id,
        notification="Решение сохранено",
        message=callback_message(callback, text, issue_keyboard(issue, miniapp_url, bot_username, role)),
    )


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
    if action == "duplicate":
        # Payload is "duplicate:<signal_id>:<candidate_issue_id>:<decision>": three
        # values do not fit the two-field form every other action uses.
        parts = callback.payload.split(":")
        if len(parts) != 4:
            await adapter.answer_callback(callback.callback_id, notification="Неизвестное действие")
            return
        await resolve_duplicate(adapter, api, callback, parts[1], parts[2], parts[3], miniapp_url, bot_username, state)
        return
    conversation_key = callback.conversation_key
    pending = dialog_key(callback.chat_id, callback.user_id)
    role = current_role(state, conversation_key, callback.user_id)
    if action == "menu":
        if value == "report":
            state and state.begin_dialog(pending, "report_text")
            await adapter.answer_callback(
                callback.callback_id,
                notification="Опишите проблему одним сообщением",
                message=callback_message(callback, "**Сообщить о проблеме**\n\nНапишите, что случилось. Если в сообщении уже есть категория и место, уточнений не будет.\n\nМожно отменить: `/cancel`", cancel_keyboard()),
            )
            return
        if value == "initiative":
            state and state.begin_dialog(pending, "initiative_text")
            await adapter.answer_callback(
                callback.callback_id,
                notification="Напишите предложение",
                message=callback_message(callback, "**Новая инициатива**\n\nОпишите предложение жителей одним сообщением. Я соберу его в инициативу и запущу неофициальный опрос.", cancel_keyboard()),
            )
            return
        if value == "houses":
            await adapter.answer_callback(callback.callback_id, notification="Выберите дом", message=callback_message(callback, "**Выберите дом для этого чата**", house_keyboard()))
            return
        if value == "issues":
            house_id = state.house_for_key(conversation_key) if state else "demo-house-a"
            status = await api.house_status(house_id, viewer_id=callback.user_id)
            personal = status.get("my_issues") or []
            personal_status = {**status, "issues": personal, "metrics": {**(status.get("metrics") or {}), "active_issues": len(personal)}}
            await adapter.answer_callback(
                callback.callback_id,
                notification="Ваши обращения",
                message=callback_message(callback, format_status(personal_status, role, "Мои обращения"), status_keyboard(personal_status, role)),
            )
            return
        if value == "status":
            house_id = state.house_for_key(conversation_key) if state else "demo-house-a"
            status = await api.house_status(house_id, role=role)
            await adapter.answer_callback(callback.callback_id, notification="Состояние обновлено", message=callback_message(callback, format_status(status, role), status_keyboard(status, role)))
            return
        if value in {"queue", "verify"}:
            house_id = state.house_for_key(conversation_key) if state else "demo-house-a"
            status = await api.house_status(house_id, viewer_id=callback.user_id if role == "resident" else None, role=role)
            if value == "verify":
                status = {**status, "issues": [item for item in status.get("issues", []) if item.get("state") == "DONE_PENDING_VERIFICATION"]}
            queue_status = {**status, "metrics": {**(status.get("metrics") or {}), "active_issues": len(status.get("issues") or [])}}
            heading = {"resident": "Проверить результат", "representative": "Требуют решения", "uk": "Новые задачи", "executor": "Мои работы"}.get(role, "Мои задачи")
            await adapter.answer_callback(
                callback.callback_id,
                notification=heading,
                message=callback_message(callback, format_status(queue_status, role, heading), status_keyboard(queue_status, role, queue_only=True)),
            )
            return
        if value == "initiatives":
            house_id = state.house_for_key(conversation_key) if state else "demo-house-a"
            status = await api.house_status(house_id)
            initiatives = status.get("initiatives") or []
            text = "**Инициативы жителей**\n\n" + ("\n\n".join(format_initiative(item) for item in initiatives) if initiatives else "Пока нет открытых инициатив.")
            rows = []
            for initiative in initiatives[:8]:
                rows.append([{"type": "callback", "text": f"Открыть · {initiative.get('title', 'Инициатива')}"[:128], "payload": f"open_initiative:{initiative['id']}"}])
            rows.append([{ "type": "callback", "text": "Предложить инициативу", "payload": "menu:initiative" }])
            rows.append([menu_button()])
            await adapter.answer_callback(callback.callback_id, notification="Инициативы жителей", message=callback_message(callback, text, inline_keyboard(rows)))
            return
        if value == "role":
            await adapter.answer_callback(
                callback.callback_id,
                notification="Выберите рабочую роль",
                message=callback_message(callback, f"**Рабочая роль участника**\n\n{role_text(role)}\n\nВ демонстрации роль определяет доступные действия. В рабочей системе она берётся из прав организации.", role_keyboard()),
            )
            return
        if value == "help":
            house_id = state.house_for_key(conversation_key) if state else "demo-house-a"
            await adapter.answer_callback(callback.callback_id, notification="Подсказка", message=callback_message(callback, help_text(house_id, role), menu_keyboard(role)))
            return
        if value == "cancel":
            state and state.clear_dialog(pending)
            await adapter.answer_callback(callback.callback_id, notification="Диалог отменён", message=callback_message(callback, "Выберите следующее действие:", menu_keyboard(role)))
            return
    if action == "role":
        if state:
            state.set_role(conversation_key, callback.user_id, value)
        selected = value if value in ROLE_LABELS else "resident"
        await adapter.answer_callback(
            callback.callback_id,
            notification=f"Роль: {ROLE_LABELS[selected]}",
            message=callback_message(callback, f"{role_text(selected)}\n\nРоль действует только в этом чате: в группе и в личке её нужно выбрать отдельно. Житель подтверждает и проверяет результат; домоуправляющий принимает решение о передаче; УК назначает работу; исполнитель выполняет её.", menu_keyboard(selected)),
        )
        return
    if action == "back":
        dialog = state.dialog(pending) if state else None
        if value == "category" and state and dialog and dialog.get("mode") == "report_zone":
            preserved = {key: item for key, item in dialog.items() if key not in {"mode", "category", "zone_choices"}}
            state.begin_dialog(pending, "report_category", **preserved)
            await adapter.answer_callback(
                callback.callback_id,
                notification="Выберите категорию",
                message=callback_message(callback, "**Что случилось?**\n\nВыберите категорию проблемы.", category_keyboard()),
            )
            return
        if value == "status":
            house_id = state.house_for_key(conversation_key) if state else "demo-house-a"
            status = await api.house_status(house_id)
            await adapter.answer_callback(callback.callback_id, notification="Вернулись к состоянию дома", message=callback_message(callback, format_status(status, role), status_keyboard(status, role)))
            return
        if state:
            state.clear_dialog(pending)
        await adapter.answer_callback(callback.callback_id, notification="Главное меню", message=callback_message(callback, "Выберите действие:", menu_keyboard(role)))
        return
    required_role = {
        "confirm_issue": "resident",
        "issue_confirm": "representative",
        "issue_submit": "representative",
        "route": "representative",
        "route_select": "representative",
        "issue_accept": "uk",
        "issue_assign": "uk",
        "order_start": "executor",
        "order_evidence": "executor",
        "order_done": "executor",
        "initiative_handoff": "representative",
        "verify_yes": "resident",
        "verify_no": "resident",
    }.get(action)
    if required_role and role != required_role:
        await adapter.answer_callback(
            callback.callback_id,
            notification=f"Нужна роль: {ROLE_LABELS[required_role]}",
            message=callback_message(callback, role_denied_text(required_role), menu_keyboard(role)),
        )
        return
    if action == "house":
        if state:
            state.set_house_key(conversation_key, value)
        await adapter.answer_callback(callback.callback_id, notification="Дом выбран", message=callback_message(callback, f"Дом переключён: {house_label(value)}\n\nТеперь сообщения в этом чате относятся к выбранному дому. Смена действует для всех участников чата.", menu_keyboard(role)))
        return
    if action == "category":
        if not state or not state.dialog(pending) or state.dialog(pending).get("mode") != "report_category":
            await adapter.answer_callback(callback.callback_id, notification="Начните с кнопки «Сообщить о проблеме»")
            return
        dialog = {key: item for key, item in state.dialog(pending).items() if key != "mode"}
        state.begin_dialog(pending, "report_zone", **dialog, category=value)
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
        dialog = state.dialog(pending) if state else None
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
        if dialog.get("signal_id"):
            result = await api.resolve_signal(str(dialog["signal_id"]), str(dialog["category"]), value)
        else:
            result = await api.process_message(message, state.house_for_key(conversation_key), manual_category=str(dialog["category"]), manual_zone_id=value)
        state.clear_dialog(pending)
        issue = result.get("issue")
        if issue:
            state.watch_issue(message, issue)
        attachments = issue_keyboard(issue, miniapp_url, bot_username, role) if issue else menu_keyboard(role)
        # answer_callback can only edit the card where it already sits, which is
        # the private chat. The house chat still has to learn that the report is
        # now registered, after the clarification it was still waiting for.
        if chat_id := dialog.get("chat_id"):
            ack = group_ack(result)
            if ack:
                await adapter.send_message(text=ack, chat_id=chat_id)
        await adapter.answer_callback(callback.callback_id, notification="Сигнал обработан", message=callback_message(callback, format_result(result, miniapp_url), attachments))
        return
    if action == "open_issue":
        issue = await api.issue(value)
        if state:
            state.watch_callback(callback, issue)
        await adapter.answer_callback(callback.callback_id, notification="Карточка проблемы", message=callback_message(callback, format_result({"issue": issue}, miniapp_url), issue_keyboard(issue, miniapp_url, bot_username, role)))
        return
    if action == "route":
        await adapter.answer_callback(
            callback.callback_id,
            notification="Выберите адресата",
            message=callback_message(callback, "**Кому передать обращение?**\n\nМаршрут не определён автоматически. Выберите адресата вручную.", route_keyboard(value)),
        )
        return
    if action == "route_select":
        issue_id, route_separator, destination = value.rpartition(":")
        if not route_separator or destination not in {"management_org", "representative"}:
            await adapter.answer_callback(callback.callback_id, notification="Не удалось выбрать адресата")
            return
        issue = await api.select_route(issue_id, destination)
        if state:
            state.watch_callback(callback, issue)
        await adapter.answer_callback(
            callback.callback_id,
            notification="Адресат выбран",
            message=callback_message(callback, format_result({"issue": issue}, miniapp_url), issue_keyboard(issue, miniapp_url, bot_username, role)),
        )
        return
    if action == "open_initiative":
        initiative = await api.initiative(value)
        await adapter.answer_callback(callback.callback_id, notification="Инициатива", message=callback_message(callback, format_initiative(initiative), initiative_keyboard(initiative, bot_username, role)))
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
            message={"text": format_result({"issue": issue, "clustered": True}, miniapp_url), "format": "markdown", "attachments": issue_keyboard(issue, miniapp_url, bot_username, role)},
        )
        return
    if action == "issue_confirm":
        issue = await api.confirm(value)
        if state:
            state.watch_callback(callback, issue)
        await adapter.answer_callback(callback.callback_id, notification="Проблема подтверждена", message=callback_message(callback, format_result({"issue": issue}, miniapp_url), issue_keyboard(issue, miniapp_url, bot_username, role)))
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
        await adapter.answer_callback(callback.callback_id, notification="Статус обновлён", message=callback_message(callback, format_result({"issue": issue}, miniapp_url), issue_keyboard(issue, miniapp_url, bot_username, role)))
        return
    if action == "initiative_handoff":
        initiative = await api.handoff(value)
        await adapter.answer_callback(callback.callback_id, notification="Результат опроса сохранён", message=callback_message(callback, format_initiative(initiative), initiative_keyboard(initiative, bot_username, role)))
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
            message={"text": format_initiative(updated), "format": "markdown", "attachments": initiative_keyboard(updated, bot_username, role)},
        )
        return
    if action in {"verify_yes", "verify_no"}:
        result = "confirmed" if action == "verify_yes" else "rejected"
        issue = await api.verify(value, callback.user_id, result)
        if state:
            # Without this the watcher keeps the state from before the check and
            # the resident stops hearing about what happens to the problem next.
            state.watch_callback(callback, issue)
        notification = "Спасибо, результат подтверждён" if result == "confirmed" else "Проблема переоткрыта"
        await adapter.answer_callback(
            callback.callback_id,
            notification=notification,
            message={"text": format_result({"issue": issue}, miniapp_url), "format": "markdown", "attachments": issue_keyboard(issue, miniapp_url, bot_username, role)},
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
        for conversation_key, watcher in conversations.items():
            previous_state = watcher.get("last_state")
            if previous_state == current_state:
                continue
            if previous_state:
                text = (
                    f"**Состояние проблемы изменилось**\n{issue.get('title')}\n"
                    f"{state_label(previous_state)} → {state_label(current_state)}\n\n"
                    f"{issue_next_step(issue)}"
                )
                role = state.role_for(conversation_key, str(watcher.get("user_id") or ""))
                attachments = (
                    issue_keyboard(issue, miniapp_url, bot_username, role)
                    if current_state == "DONE_PENDING_VERIFICATION"
                    else notification_keyboard(issue)
                )
                # The house chat follows the job with one line, so neighbours see
                # that something is being done; the card and the actions for the
                # next role stay with the person who reported it.
                if chat_id := watcher.get("chat_id"):
                    await adapter.send_message(
                        text=f"🔧 {short_issue_title(issue)}: {state_label(previous_state)} → {state_label(current_state)}",
                        chat_id=chat_id,
                    )
                try:
                    await adapter.send_message(text=text, user_id=watcher.get("user_id"), attachments=attachments)
                except MaxAdapterError:
                    LOGGER.warning("Direct message to user %s failed; posting the update in chat %s", watcher.get("user_id"), watcher.get("chat_id"))
                    if watcher.get("chat_id"):
                        await adapter.send_message(text=text, chat_id=watcher["chat_id"], attachments=attachments)
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
                        try:
                            await adapter.answer_callback(callback.callback_id, notification=detail[:200])
                        except (MaxAdapterError, httpx.HTTPError):
                            LOGGER.exception("Could not answer failed MAX callback %s", callback.callback_id)
                    except (MaxAdapterError, httpx.HTTPError, OSError, KeyError, ValueError) as exc:
                        LOGGER.exception("MAX callback %s failed", callback.payload)
                        try:
                            await adapter.answer_callback(callback.callback_id, notification="Не удалось выполнить действие. Повторите ещё раз.")
                        except (MaxAdapterError, httpx.HTTPError):
                            LOGGER.exception("Could not answer MAX callback failure %s", callback.callback_id)
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
