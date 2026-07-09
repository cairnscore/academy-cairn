"""Demo 1 — trust accumulates.

A real Academy agent fetches a data source. The first time, Cairn has no track
record for that source (confidence 0.0 — "no data", not "bad"), so the guard
just proceeds. Each successful fetch rates the source; after the agent flushes,
the source's reputation has moved — earned from ground-truth outcomes, no LLM.

The only trust-specific code is the one `@cairn_guarded` line — the agent is an
ordinary Academy agent, and the decorator provisions and flushes Cairn itself.

Run:  CAIRN_NAMESPACE=demo uv run python examples/01_trust_accumulates.py
"""

from __future__ import annotations

import asyncio

from _demo import academy, bar, demo_entity, reader
from academy.agent import Agent, action

from academy_cairn import EntityRef, cairn_guarded

WEATHER_API = demo_entity("weather-api")


class WeatherAgent(Agent):  # a completely ordinary Academy agent
    @action
    @cairn_guarded(type="data_source", id_from="url")  # <-- the only line you add
    async def fetch(self, url: str) -> str:
        # A real agent would hit the network here. The guard checks the
        # source's reputation before this runs and rates it after.
        return "72F, sunny"


async def main() -> None:
    read = reader()
    ref = EntityRef(type="data_source", external_id=WEATHER_API)

    before = await read.get_score(ref)
    print(f"Source: {WEATHER_API}\n")
    print("Before any interactions:")
    print(f"  trust    {bar(before.composite_score)} {before.composite_score:.2f}")
    print(f"  evidence {bar(before.confidence)} {before.confidence:.2f}  "
          f"({'no track record' if before.confidence == 0 else 'some evidence'})\n")

    async with academy() as manager:
        agent = await manager.launch(WeatherAgent, name="weather-agent")
        print("A WeatherAgent fetches 8 times (each fetch rates the source)...")
        for _ in range(8):
            await agent.fetch(url=WEATHER_API)
        # On shutdown (context exit) the agent flushes its ratings to Cairn.

    after = await read.get_score(ref)
    print("\nAfter 8 good interactions:")
    print(f"  trust    {bar(after.composite_score)} {after.composite_score:.2f}")
    print(f"  evidence {bar(after.confidence)} {after.confidence:.2f}\n")
    print("The source earned a track record from what actually happened.")

    await read.aclose()


if __name__ == "__main__":
    asyncio.run(main())
