import asyncio

from app.integrations.max_adapter import MockMaxAdapter


def test_mock_max_adapter_is_honest():
    adapter = MockMaxAdapter()
    bot = asyncio.run(adapter.get_bot())
    keyboard = [{"type": "inline_keyboard", "payload": {"buttons": []}}]
    sent = asyncio.run(adapter.send_message(text="test", user_id="1", attachments=keyboard))
    answered = asyncio.run(adapter.answer_callback("cb-1", notification="Учтено"))
    updates = asyncio.run(adapter.get_updates(marker=7))
    assert bot["simulated"] is True
    assert sent["simulated"] is True
    assert sent["attachments"] == keyboard
    assert answered["callback_id"] == "cb-1"
    assert updates == {"updates": [], "marker": 7, "simulated": True}
    assert adapter.mode == "SIMULATED"
