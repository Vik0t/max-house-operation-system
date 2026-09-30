import asyncio
from abc import ABC, abstractmethod
from typing import Any

import httpx

from ..settings import Settings


class MaxAdapterError(RuntimeError):
    pass


class MaxAdapter(ABC):
    mode: str

    @abstractmethod
    async def get_bot(self) -> dict[str, Any]: ...

    @abstractmethod
    async def send_message(
        self,
        *,
        text: str,
        chat_id: str | None = None,
        user_id: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def edit_message(
        self,
        message_id: str,
        *,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def answer_callback(
        self,
        callback_id: str,
        *,
        notification: str | None = None,
        message: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def check_chat_permissions(self, chat_id: str) -> dict[str, Any]: ...

    @abstractmethod
    async def get_updates(
        self,
        *,
        marker: int | None = None,
        timeout: int = 30,
        limit: int = 100,
        update_types: list[str] | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def get_subscriptions(self) -> list[dict[str, Any]]: ...


class MockMaxAdapter(MaxAdapter):
    mode = "SIMULATED"

    async def get_bot(self) -> dict[str, Any]:
        return {"is_bot": True, "first_name": "ДомПульс Demo", "username": "dompuls_demo_bot", "simulated": True}

    async def send_message(
        self,
        *,
        text: str,
        chat_id: str | None = None,
        user_id: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {"delivered": True, "simulated": True, "chat_id": chat_id, "user_id": user_id, "text": text, "attachments": attachments or []}

    async def edit_message(
        self,
        message_id: str,
        *,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {"success": True, "simulated": True, "message_id": message_id, "text": text, "attachments": attachments or []}

    async def answer_callback(
        self,
        callback_id: str,
        *,
        notification: str | None = None,
        message: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"success": True, "simulated": True, "callback_id": callback_id, "notification": notification, "message": message}

    async def check_chat_permissions(self, chat_id: str) -> dict[str, Any]:
        return {"chat_id": chat_id, "permissions": [], "has_read_all_messages": False, "simulated": True}

    async def get_updates(
        self,
        *,
        marker: int | None = None,
        timeout: int = 30,
        limit: int = 100,
        update_types: list[str] | None = None,
    ) -> dict[str, Any]:
        return {"updates": [], "marker": marker, "simulated": True}

    async def get_subscriptions(self) -> list[dict[str, Any]]:
        return []


class RealMaxAdapter(MaxAdapter):
    mode = "REAL"

    def __init__(self, settings: Settings):
        if not settings.max_bot_token:
            raise MaxAdapterError("MAX_MODE=real requires MAX_BOT_TOKEN")
        self.base_url = settings.max_api_base.rstrip("/")
        self.headers = {"Authorization": settings.max_bot_token}
        self.verify: bool | str = settings.max_ca_bundle or True

    async def _request(self, method: str, path: str, *, request_timeout: float = 8.0, **kwargs) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=request_timeout, verify=self.verify) as client:
                    response = await client.request(method, f"{self.base_url}{path}", headers=self.headers, **kwargs)
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                if status and status < 500 and status != 429:
                    break
                if attempt < 2:
                    await asyncio.sleep(0.2 * (2**attempt))
        raise MaxAdapterError(f"MAX API request failed: {type(last_error).__name__}") from last_error

    async def get_bot(self) -> dict[str, Any]:
        return await self._request("GET", "/me")

    async def send_message(
        self,
        *,
        text: str,
        chat_id: str | None = None,
        user_id: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not chat_id and not user_id:
            raise MaxAdapterError("chat_id or user_id is required")
        params = {"chat_id": chat_id} if chat_id else {"user_id": user_id}
        body: dict[str, Any] = {"text": text, "format": "markdown"}
        if attachments:
            body["attachments"] = attachments
        return await self._request("POST", "/messages", params=params, json=body)

    async def edit_message(
        self,
        message_id: str,
        *,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text, "format": "markdown", "notify": False}
        if attachments is not None:
            body["attachments"] = attachments
        result = await self._request("PUT", "/messages", params={"message_id": message_id}, json=body)
        if isinstance(result, dict) and result.get("success") is False:
            raise MaxAdapterError("MAX rejected the message edit")
        return result

    async def answer_callback(
        self,
        callback_id: str,
        *,
        notification: str | None = None,
        message: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if notification:
            body["notification"] = notification
        if message:
            body["message"] = message
        return await self._request("POST", "/answers", params={"callback_id": callback_id}, json=body)

    async def check_chat_permissions(self, chat_id: str) -> dict[str, Any]:
        member = await self._request("GET", f"/chats/{chat_id}/members/me")
        permissions = member.get("permissions") or []
        return {
            "chat_id": chat_id,
            "permissions": permissions,
            "has_read_all_messages": "read_all_messages" in permissions,
            "simulated": False,
        }

    async def get_updates(
        self,
        *,
        marker: int | None = None,
        timeout: int = 30,
        limit: int = 100,
        update_types: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {"timeout": timeout, "limit": limit}
        if marker is not None:
            params["marker"] = marker
        if update_types:
            params["types"] = ",".join(update_types)
        return await self._request("GET", "/updates", params=params, request_timeout=timeout + 10)

    async def get_subscriptions(self) -> list[dict[str, Any]]:
        result = await self._request("GET", "/subscriptions")
        if isinstance(result, list):
            return result
        return result.get("subscriptions", [])


def build_max_adapter(settings: Settings) -> MaxAdapter:
    return RealMaxAdapter(settings) if settings.max_mode == "real" else MockMaxAdapter()
