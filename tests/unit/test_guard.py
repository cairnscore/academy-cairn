import pytest

from academy_cairn.entity import Reading
from academy_cairn.guard import CairnTrustError, TrustPolicy, cairn_guarded


class FakeCairn:
    def __init__(self, reading):
        self._reading = reading
        self.enqueued = []

        class C:
            default_weight = 0.3

        self.config = C()
    async def get_score(self, ref): return self._reading
    def enqueue(self, event): self.enqueued.append(event)


class Agent:
    def __init__(self, cairn): self.cairn = cairn

    @cairn_guarded(
        type="data_source", id_from="url", policy=TrustPolicy(on_low="block")
    )
    async def fetch(self, url: str) -> str:
        return "data"

    @cairn_guarded(type="data_source", id_from="url")
    async def boom(self, url: str) -> str:
        raise ValueError("kaboom")


@pytest.mark.asyncio
async def test_success_enqueues_rating():
    agent = Agent(FakeCairn(Reading.no_data()))
    assert await agent.fetch(url="https://a/v1") == "data"
    assert len(agent.cairn.enqueued) == 1
    assert agent.cairn.enqueued[0].reviewee.external_id == "https://a/v1"


@pytest.mark.asyncio
async def test_block_only_with_confidence():
    # low score but no confidence ⇒ proceed
    agent = Agent(FakeCairn(Reading(composite_score=0.1, confidence=0.0)))
    assert await agent.fetch(url="https://a/v1") == "data"
    # low score WITH confidence ⇒ block
    agent2 = Agent(FakeCairn(Reading(composite_score=0.1, confidence=0.9)))
    with pytest.raises(CairnTrustError):
        await agent2.fetch(url="https://a/v1")


@pytest.mark.asyncio
async def test_exception_reraises_and_rates_low():
    agent = Agent(FakeCairn(Reading.no_data()))
    with pytest.raises(ValueError):
        await agent.boom(url="https://a/v1")
    assert agent.cairn.enqueued[0].score == 0.2


@pytest.mark.asyncio
async def test_noop_without_cairn():
    class Bare:
        cairn = None
        @cairn_guarded(type="data_source", id_from="url")
        async def fetch(self, url: str) -> str: return "ok"
    assert await Bare().fetch(url="https://a/v1") == "ok"


def test_composes_under_action_marker():
    # simulate Academy's @action marking the wrapper
    from academy_cairn.guard import cairn_guarded
    @cairn_guarded(type="data_source", id_from="url")
    async def fetch(self, url: str): return "x"
    fetch._agent_method_type = "action"  # @action would set this on the wrapper
    assert fetch._agent_method_type == "action"
    assert fetch.__name__ == "fetch"  # functools.wraps preserved identity
