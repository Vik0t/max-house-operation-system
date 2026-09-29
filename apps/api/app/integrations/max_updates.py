from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any


@dataclass(frozen=True)
class IncomingMaxMessage:
    text: str
    user_id: str
    chat_id: str | None
    external_id: str
    attachments: list[dict[str, Any]]
    sender_is_bot: bool = False

    @property
    def conversation_key(self) -> str:
        return f"chat:{self.chat_id}" if self.chat_id else f"user:{self.user_id}"


@dataclass(frozen=True)
class IncomingMaxCallback:
    callback_id: str
    payload: str
    user_id: str
    chat_id: str | None

    @property
    def conversation_key(self) -> str:
        return f"chat:{self.chat_id}" if self.chat_id else f"user:{self.user_id}"


def parse_incoming_callback(update: dict[str, Any]) -> IncomingMaxCallback | None:
    if update.get("update_type") != "message_callback":
        return None
    callback = update.get("callback") or {}
    message = update.get("message") or {}
    recipient = message.get("recipient") or {}
    user = callback.get("user") or {}
    callback_id = callback.get("callback_id")
    payload = callback.get("payload")
    user_id = user.get("user_id")
    if callback_id is None or payload is None or user_id is None:
        return None
    chat_id = recipient.get("chat_id") or update.get("chat_id")
    return IncomingMaxCallback(
        callback_id=str(callback_id),
        payload=str(payload),
        user_id=str(user_id),
        chat_id=str(chat_id) if chat_id is not None else None,
    )


def parse_incoming_message(update: dict[str, Any]) -> IncomingMaxMessage | None:
    if update.get("update_type") != "message_created":
        return None
    message = update.get("message") or {}
    body = message.get("body") or {}
    sender = message.get("sender") or {}
    recipient = message.get("recipient") or {}
    text = str(body.get("text") or "").strip()
    user_id = sender.get("user_id")
    attachments = body.get("attachments") or []
    if not text and image_url(attachments):
        text = "[Фото]"
    if not text or user_id is None:
        return None
    chat_id = recipient.get("chat_id") or update.get("chat_id")
    message_id = body.get("mid") or message.get("id")
    if message_id is None:
        message_id = f"{update.get('timestamp', 'unknown')}:{user_id}"
    return IncomingMaxMessage(
        text=text,
        user_id=str(user_id),
        chat_id=str(chat_id) if chat_id is not None else None,
        external_id=str(message_id),
        attachments=attachments,
        sender_is_bot=bool(sender.get("is_bot")),
    )


def image_url(attachments: list[dict[str, Any]]) -> str | None:
    """Select an actual HTTPS image URL from a received MAX attachment."""
    for item in attachments:
        if item.get("type") != "image":
            continue
        payload = item.get("payload") or {}
        candidates = [payload.get("url"), item.get("url")]
        photos = payload.get("photos") or {}
        if isinstance(photos, dict):
            for photo in photos.values():
                if isinstance(photo, dict):
                    candidates.append(photo.get("url"))
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.startswith("https://") and len(candidate) <= 2000:
                return candidate
    return None


def polling_is_active(state_path: str, poll_timeout: int, *, now: float | None = None) -> bool:
    try:
        age = (time.time() if now is None else now) - Path(state_path).stat().st_mtime
    except OSError:
        return False
    return age <= max(15, poll_timeout * 3)
