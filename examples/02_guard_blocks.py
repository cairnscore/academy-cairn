"""Demo 2 — reputations diverge, and the guard acts on them.

Two data sources: one reliable, one flaky. After a handful of real interactions
their reputations pull apart — the reliable one rises, the flaky one falls. A
strict agent then refuses to use a source it can't trust: the guard raises
CairnTrustError before the action ever runs. Crucially it only blocks when there
is *evidence* — an unknown source (no track record) is always allowed.

Run:  CAIRN_NAMESPACE=demo uv run python examples/02_guard_blocks.py
"""

from __future__ import annotations

import asyncio

from _demo import academy, bar, demo_entity, reader
from academy.agent import Agent, action

from academy_cairn import (
    CairnTrustError,
    EntityRef,
    TrustPolicy,
    cairn_guarded,
)

RELIABLE = demo_entity("reliable-api")
FLAKY = demo_entity("flaky-api")
UNKNOWN = demo_entity("brand-new-api")

# A strict agent: block a source whose trust is below 0.5, but only once there
# is enough evidence to be confident. Never block on "no data".
STRICT = TrustPolicy(min_score=0.5, min_confidence=0.3, on_low="block")


class SeederAgent(Agent):
    """Builds a track record: the reliable source succeeds, the flaky one times out."""

    @action
    @cairn_guarded(type="data_source", id_from="url")
    async def fetch(self, url: str) -> str:
        if url == FLAKY:
            raise TimeoutError("source timed out")
        return "ok"


class ResearchAgent(Agent):
    @action
    @cairn_guarded(type="data_source", id_from="url", policy=STRICT)
    async def query(self, url: str) -> str:
        return f"<results from {url}>"


async def main() -> None:
    read = reader()

    # Phase 1 — build reputations with real interactions.
    async with academy() as manager:
        seeder = await manager.launch(SeederAgent, name="seeder")
        for _ in range(8):
            await seeder.fetch(url=RELIABLE)
            try:
                await seeder.fetch(url=FLAKY)  # guard rates the failure, then re-raises
            except TimeoutError:
                pass
    # seeder shutdown flushed its ratings to Cairn

    print("After 8 interactions each:\n")
    for label, url in [("reliable", RELIABLE), ("flaky", FLAKY)]:
        r = await read.get_score(EntityRef(type="data_source", external_id=url))
        print(f"  {label:8s} trust {bar(r.composite_score)} {r.composite_score:.2f} "
              f"(evidence {r.confidence:.2f})")

    # Phase 2 — a strict agent acts on those reputations.
    print("\nA strict agent (block below 0.5 trust) tries each source:\n")
    async with academy() as manager:
        agent = await manager.launch(ResearchAgent, name="research-agent")
        for label, url in [("reliable ", RELIABLE), ("flaky    ", FLAKY),
                           ("brand-new", UNKNOWN)]:
            try:
                await agent.query(url=url)
                print(f"  {label}  ✅ allowed")
            except CairnTrustError:
                print(f"  {label}  ⛔ blocked — trust too low")
    print("\nThe flaky source is refused; the brand-new one is allowed "
          "(no evidence ⇒ never blocked).")

    await read.aclose()


if __name__ == "__main__":
    asyncio.run(main())
