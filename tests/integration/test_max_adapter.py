import asyncio

from app.integrations.max_adapter import MockMaxAdapter


def test_mock_max_adapter_is_honest():
    adapter = MockMaxAdapter()
    bot = asyncio.run(adapter.get_bot())
    sent = asyncio.run(adapter.send_message(text="test", user_id="1"))
    assert bot["simulated"] is True
    assert sent["simulated"] is True
    assert adapter.mode == "SIMULATED"
