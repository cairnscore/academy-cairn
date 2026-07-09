"""Demo 3 — score your peer agents from ground truth.

Agents call other agents. `rated(handle)` wraps a peer's handle so every call is
scored from what actually happened — did the peer answer, without error, in time
— not from analyzing its text. Here a coordinator agent delegates work to two
real peer agents: a solid analyzer and a flaky worker that keeps crashing. Their
reputations reflect reality, so the coordinator can route work to whoever it can
trust.

Run:  CAIRN_NAMESPACE=demo uv run python examples/03_peer_scoring.py
"""

from __future__ import annotations

import asyncio
import uuid

from _demo import academy, bar, reader
from academy.agent import Agent, action
from academy.handle import Handle

from academy_cairn import EntityRef, rated


class Analyzer(Agent):
    @action
    async def analyze(self, data: str) -> str:
        return f"analysis of {data}"


class FlakyWorker(Agent):
    def __init__(self) -> None:
        super().__init__()
        self._calls = 0

    @action
    async def analyze(self, data: str) -> str:
        self._calls += 1
        if self._calls % 3 != 0:  # succeeds only every third call
            raise RuntimeError("worker crashed")
        return f"analysis of {data}"


class Coordinator(Agent):  # a plain Academy agent
    def __init__(self, analyzer: Handle, worker: Handle) -> None:
        super().__init__()
        self._analyzer = analyzer
        self._worker = worker

    @action
    async def delegate(self, rounds: int) -> None:
        # rated(handle, agent=self) uses (and lazily sets up) this agent's
        # Cairn client — no mixin required.
        analyzer = rated(self._analyzer, agent=self)
        worker = rated(self._worker, agent=self)
        for _ in range(rounds):
            await analyzer.analyze("dataset")  # scored automatically
            try:
                await worker.analyze("dataset")  # rated even when it raises
            except RuntimeError:
                pass


async def main() -> None:
    read = reader()
    run = uuid.uuid4().hex[:6]  # fresh peer identities per run
    analyzer_name, worker_name = f"analyzer-{run}", f"flaky-worker-{run}"

    print("Coordinator delegates 8 tasks to each peer...\n")
    async with academy() as manager:
        analyzer = await manager.launch(Analyzer, name=analyzer_name)
        worker = await manager.launch(FlakyWorker, name=worker_name)
        coordinator = await manager.launch(Coordinator, args=(analyzer, worker))
        await coordinator.delegate(8)
    # coordinator shutdown flushed its peer ratings to Cairn

    ns = read.config.namespace
    print("Peer reputations (from real invocation outcomes):\n")
    scores = {}
    for label, name in [("analyzer", analyzer_name), ("flaky-worker", worker_name)]:
        ref = EntityRef(type="agent", external_id=f"agent://academy/{ns}/{name}")
        r = await read.get_score(ref)
        scores[label] = r.composite_score
        print(f"  {label:13s} {bar(r.composite_score)} {r.composite_score:.2f} "
              f"(evidence {r.confidence:.2f})")

    best = max(scores, key=scores.get)
    print(f"\nThe coordinator now knows to route work to the {best!r} — "
          "earned, not assumed.")

    await read.aclose()


if __name__ == "__main__":
    asyncio.run(main())
