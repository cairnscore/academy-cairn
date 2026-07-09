import pickle

import pytest

from academy_cairn.peers import rated


class FakeCairn:
    def __init__(self):
        self.enqueued = []

        class C:
            default_weight = 0.3

        self.config = C()

    def enqueue(self, e):
        self.enqueued.append(e)


class FakeAgentId:
    uid = "peer1234abcd"
    name = "analyzer"


class FakeHandle:
    """Stand-in for academy Handle: all calls funnel through action()."""

    def __init__(self, fail=False):
        self.agent_id = FakeAgentId()
        self._fail = fail

    async def action(self, name, /, *args, **kwargs):
        if self._fail:
            raise RuntimeError("peer down")
        return f"{name}:ok"

    def __reduce__(self):
        return (FakeHandle, ())


@pytest.mark.asyncio
async def test_success_delegates_and_rates():
    cairn = FakeCairn()
    h = rated(FakeHandle(), cairn=cairn)
    assert await h.action("analyze") == "analyze:ok"
    assert len(cairn.enqueued) == 1
    ev = cairn.enqueued[0]
    assert ev.reviewee.external_id.endswith("/analyzer")
    assert ev.reviewee.type == "agent"
    assert ev.score == 0.75


@pytest.mark.asyncio
async def test_failure_rates_low_and_reraises():
    cairn = FakeCairn()
    h = rated(FakeHandle(fail=True), cairn=cairn)
    with pytest.raises(RuntimeError):
        await h.action("analyze")
    assert cairn.enqueued[0].score == 0.2


def test_passthrough_attribute():
    h = rated(FakeHandle(), cairn=FakeCairn())
    assert h.agent_id.name == "analyzer"


def test_serialization_degrades_to_plain_handle():
    h = rated(FakeHandle(), cairn=FakeCairn())
    restored = pickle.loads(pickle.dumps(h))
    assert isinstance(restored, FakeHandle)  # not a RatedHandle


@pytest.mark.asyncio
async def test_attribute_style_call_is_rated():
    cairn = FakeCairn()
    h = rated(FakeHandle(), cairn=cairn)
    result = await h.analyze("data")
    assert result == "analyze:ok"
    assert len(cairn.enqueued) == 1
    ev = cairn.enqueued[0]
    assert ev.reviewee.type == "agent"
    assert ev.reviewee.external_id.startswith("agent://academy/")
    assert ev.reviewee.external_id.endswith("/analyzer")


def test_real_attribute_passes_through_and_does_not_rate():
    cairn = FakeCairn()
    h = rated(FakeHandle(), cairn=cairn)
    assert h.agent_id.name == "analyzer"
    assert cairn.enqueued == []


class FailingCairn(FakeCairn):
    def enqueue(self, e):
        raise RuntimeError("enqueue exploded")


@pytest.mark.asyncio
async def test_enqueue_failure_does_not_mask_peer_exception():
    cairn = FailingCairn()
    h = rated(FakeHandle(fail=True), cairn=cairn)
    with pytest.raises(RuntimeError, match="peer down"):
        await h.action("analyze")


@pytest.mark.asyncio
async def test_rated_with_agent_resolves_client(monkeypatch):
    cairn = FakeCairn()
    monkeypatch.setattr("academy_cairn.peers.ensure_client", lambda agent: cairn)
    h = rated(FakeHandle(), agent=object())
    assert await h.action("analyze") == "analyze:ok"
    assert len(cairn.enqueued) == 1


def test_rated_requires_cairn_or_agent():
    with pytest.raises(TypeError):
        rated(FakeHandle())


@pytest.mark.asyncio
async def test_rated_none_client_delegates_without_rating(monkeypatch):
    # agent= resolves to None (trust disabled) -> delegate the call, don't rate,
    # and don't crash.
    monkeypatch.setattr("academy_cairn.peers.ensure_client", lambda agent: None)
    h = rated(FakeHandle(), agent=object())
    assert await h.action("analyze") == "analyze:ok"
