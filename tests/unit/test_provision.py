import pytest

from academy_cairn.client import CairnClient
from academy_cairn.provision import ensure_client


class FakeAgentId:
    uid = "abcd1234ef"
    name = "worker"


class FakeAgent:
    agent_id = FakeAgentId()

    def __init__(self) -> None:
        self.original_shutdown_called = False

    async def agent_on_shutdown(self) -> None:
        self.original_shutdown_called = True


def _offline_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CAIRN_OFFLINE", "1")
    monkeypatch.setenv("CAIRN_KEY_DIR", str(tmp_path / "keys"))


@pytest.mark.asyncio
async def test_provisions_from_agent_id_and_caches(monkeypatch, tmp_path):
    _offline_env(monkeypatch, tmp_path)
    agent = FakeAgent()
    client = ensure_client(agent)
    assert isinstance(client, CairnClient)
    assert agent.cairn is client  # cached on the instance
    assert ensure_client(agent) is client  # idempotent, no re-provision


@pytest.mark.asyncio
async def test_shutdown_flushes_then_calls_original(monkeypatch, tmp_path):
    _offline_env(monkeypatch, tmp_path)
    agent = FakeAgent()
    ensure_client(agent)
    # ensure_client wrapped agent_on_shutdown; calling it must flush+close
    # (no-op offline) and still invoke the agent's original shutdown.
    await agent.agent_on_shutdown()
    assert agent.original_shutdown_called is True


def test_uses_existing_cairn_without_reprovisioning():
    sentinel = object()

    class WithClient:
        cairn = sentinel

    assert ensure_client(WithClient()) is sentinel


def test_returns_none_without_agent_id(monkeypatch, tmp_path):
    _offline_env(monkeypatch, tmp_path)

    class Bare:
        pass

    assert ensure_client(Bare()) is None


def test_returns_none_when_disabled(monkeypatch, tmp_path):
    _offline_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CAIRN_ENABLED", "0")
    assert ensure_client(FakeAgent()) is None


@pytest.mark.asyncio
async def test_starts_background_flusher_when_online(monkeypatch, tmp_path):
    monkeypatch.setenv("CAIRN_KEY_DIR", str(tmp_path / "keys"))  # online
    monkeypatch.setenv("CAIRN_FLUSH_INTERVAL_S", "999")  # won't fire during test
    agent = FakeAgent()
    client = ensure_client(agent)
    assert agent._cairn_flush_task is not None
    agent._cairn_flush_task.cancel()  # cleanup; prevents any network flush
    await client.aclose()
