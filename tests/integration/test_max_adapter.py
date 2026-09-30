import asyncio

from app.integrations.max_adapter import MockMaxAdapter, RealMaxAdapter
from app.settings import Settings


def test_mock_max_adapter_is_honest():
    adapter = MockMaxAdapter()
    bot = asyncio.run(adapter.get_bot())
    keyboard = [{"type": "inline_keyboard", "payload": {"buttons": []}}]
    sent = asyncio.run(adapter.send_message(text="test", user_id="1", attachments=keyboard))
    answered = asyncio.run(adapter.answer_callback("cb-1", notification="Учтено"))
    edited = asyncio.run(adapter.edit_message("mid-1", text="Обновлено", attachments=keyboard))
    updates = asyncio.run(adapter.get_updates(marker=7))
    assert bot["simulated"] is True
    assert sent["simulated"] is True
    assert sent["attachments"] == keyboard
    assert answered["callback_id"] == "cb-1"
    assert edited["message_id"] == "mid-1"
    assert updates == {"updates": [], "marker": 7, "simulated": True}
    assert adapter.mode == "SIMULATED"


def test_real_adapter_edits_group_card_without_push(monkeypatch):
    calls = []

    async def fake_request(self, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"success": True}

    monkeypatch.setattr(RealMaxAdapter, "_request", fake_request)
    adapter = RealMaxAdapter(Settings(max_mode="real", max_bot_token="test-only-token"))
    keyboard = [{"type": "inline_keyboard", "payload": {"buttons": []}}]
    asyncio.run(adapter.edit_message("mid-1", text="Лифт в работе", attachments=keyboard))
    assert calls == [("PUT", "/messages", {
        "params": {"message_id": "mid-1"},
        "json": {"text": "Лифт в работе", "format": "markdown", "notify": False, "attachments": keyboard},
    })]
