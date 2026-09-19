import asyncio

from app.integrations.max_adapter import MockMaxAdapter


def test_mock_max_adapter_is_honest():
    adapter = MockMaxAdapter()
    bot = asyncio.run(adapter.get_bot())
    sent = asyncio.run(adapter.send_message(text="test", user_id="1"))
    updates = asyncio.run(adapter.get_updates(marker=7))
    assert bot["simulated"] is True
    assert sent["simulated"] is True
    assert updates == {"updates": [], "marker": 7, "simulated": True}
    assert adapter.mode == "SIMULATED"
