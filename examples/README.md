# academy-cairn — demos

Three small, runnable demos that show trust-aware Academy agents in action. Each
one launches **real Academy agents** (on Academy's in-process `LocalExchange`)
and talks to a **live Cairn** service — the numbers below are real, not mocked.

The whole idea: an agent checks a resource's reputation *before* it acts, and
records what actually happened *after* — building a shared, ground-truth memory
of trust across data sources, tools, and peer agents. No LLM involved.

## Setup

```bash
uv sync --extra dev              # installs academy-cairn + academy-py
export CAIRN_NAMESPACE=demo      # groups these demos' agent identities
```

The demos default to the hosted Cairn at `https://api.cairnscore.ai`. Point them
at your own by setting `CAIRN_BASE_URL` (e.g. a local `cairn-service` via its
`make up`). Reads are unauthenticated; the first rating an agent submits lazily
mints an API key and caches it under `~/.cairn/academy/keys`.

## The one thing to notice

In every demo, the *only* trust-specific code is **one decorator line** on an
otherwise ordinary Academy agent:

```python
class WeatherAgent(Agent):                             # unchanged Academy agent
    @action
    @cairn_guarded(type="data_source", id_from="url")  # <-- the only line you add
    async def fetch(self, url: str) -> str:
        ...
```

`@cairn_guarded` checks the resource's score before the action runs and rates
the outcome after. On first use it lazily provisions a Cairn client from the
agent's identity and flushes ratings when the agent shuts down — no base class,
no setup. (Peer rating is the same idea: `rated(peer_handle, agent=self)`.)

> Prefer explicit wiring, or want a background flusher tuned for a long-lived
> agent? Add `CairnAgentMixin` to the agent's bases and it owns the client
> lifecycle instead. It's optional — the decorator works without it.

---

## 1. Trust accumulates

`uv run python examples/01_trust_accumulates.py`

A source starts with **no track record** — Cairn returns `0.5 / confidence 0.0`,
which the guard treats as "no data", never as "bad". After eight good fetches,
the source has earned a reputation:

```
Before any interactions:
  trust    ██████████░░░░░░░░░░ 0.50
  evidence ░░░░░░░░░░░░░░░░░░░░ 0.00  (no track record)

After 8 good interactions:
  trust    ███████████░░░░░░░░░ 0.56
  evidence █████████░░░░░░░░░░░ 0.44
```

The evidence bar rising off zero is the signal: the source now has a track
record built from real outcomes.

## 2. Reputations diverge, and the guard acts

`uv run python examples/02_guard_blocks.py`

Two sources — one reliable, one that keeps timing out — pull apart after eight
interactions each. Then a **strict** agent (`TrustPolicy(min_score=0.5,
on_low="block")`) tries to use each one:

```
After 8 interactions each:
  reliable trust ███████████░░░░░░░░░ 0.56 (evidence 0.44)
  flaky    trust █████████░░░░░░░░░░░ 0.43 (evidence 0.44)

A strict agent (block below 0.5 trust) tries each source:
  reliable   ✅ allowed
  flaky      ⛔ blocked — trust too low
  brand-new  ✅ allowed
```

The flaky source is refused (`CairnTrustError` is raised before the action
runs), the trusted one passes, and a **brand-new** source is allowed — the guard
never blocks on no-data, so unknown resources aren't punished for being new.

## 3. Score your peer agents

`uv run python examples/03_peer_scoring.py`

Agents call other agents. `rated(handle)` wraps a peer's handle so every call is
scored from **what actually happened** — did the peer answer, without error, in
time. A coordinator delegates work to a solid analyzer and a flaky worker:

```
Peer reputations (from real invocation outcomes):
  analyzer      ███████████░░░░░░░░░ 0.56 (evidence 0.44)
  flaky-worker  █████████░░░░░░░░░░░ 0.46 (evidence 0.44)

The coordinator now knows to route work to the 'analyzer' — earned, not assumed.
```

The rating comes from ground truth (the call raised, or it didn't), not from
inspecting the peer's output. Wrapping is a one-liner and identical for a real
remote handle:

```python
analyzer = rated(peer_handle, agent=self)
result = await analyzer.analyze(data)   # transparently scored
```

---

## Notebook

`examples/demo.ipynb` runs the same three scenarios cell-by-cell — handy for
walking an audience through it live.

## Notes for presenting

- Every run uses a **fresh** entity id, so you always start from `0.50 / 0.00`
  and the story is reproducible.
- Agents flush their ratings on shutdown, so the score you read after a demo
  reflects the interactions you just ran.
- Trust moves *toward* the rating as evidence accumulates and decays over time
  (a 3-day half-life) — so reputation is maintained, not frozen.
