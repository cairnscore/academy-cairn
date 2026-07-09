# academy-cairn

Trust-aware [Academy](https://github.com/academy-agents/academy) agents, backed
by [Cairn](https://cairnscore.ai) reputation scores.

An Academy agent checks a resource's reputation **before** it acts on it, and
records what actually happened **after** — building a shared, ground-truth memory
of trust across data sources, tools (capabilities), and peer agents. It works
from real invocation outcomes (did the call succeed, without error, in time), not
from analyzing text. No LLM involved.

Adding it to an existing agent is one line:

```python
from academy.agent import Agent, action
from academy_cairn import cairn_guarded

class WeatherAgent(Agent):                             # an ordinary Academy agent
    @action
    @cairn_guarded(type="data_source", id_from="url")  # ← the only line you add
    async def fetch(self, url: str) -> str:
        ...
```

That's it. The decorator checks the source's score before `fetch` runs, rates the
outcome after, and flushes ratings to Cairn when the agent shuts down — no base
class, no setup.

## Install

Not yet on PyPI — install from source:

```bash
uv add "academy-cairn @ git+https://github.com/cairnscore/academy-cairn"
# or, in a clone:  uv sync --extra dev
```

Requires Python ≥ 3.10 and `academy-py`. By default it talks to the hosted Cairn
service at `https://api.cairnscore.ai`; point it elsewhere with `CAIRN_BASE_URL`.
Reads are unauthenticated; the first rating an agent submits lazily mints an API
key for its identity and caches it under `~/.cairn/academy/keys`.

## What you get

**A guard that composes with `@action`.** `@cairn_guarded` reads the resource's
score first and applies a policy, then rates the outcome:

```python
from academy_cairn import cairn_guarded, TrustPolicy

@action
@cairn_guarded(
    type="capability",                 # data_source | capability | agent
    id_from="endpoint",                # a parameter name, or a callable → EntityRef
    policy=TrustPolicy(min_score=0.5, on_low="block"),  # default policy just logs
)
async def call_tool(self, endpoint: str, payload: dict) -> dict:
    ...
```

- `on_low` is `"log"` (default), `"warn"`, or `"block"`. `block` raises
  `CairnTrustError` **before** the action runs — but only when there's enough
  evidence (`confidence ≥ min_confidence`). An unknown resource (no track record)
  is always allowed; new resources aren't punished for being new.
- On success it records a good rating; on an exception it records a low one (with
  the exception type as a failure mode) and re-raises the original error.

**Peer-agent scoring.** Wrap a handle to score a peer from what actually happened
when you call it:

```python
from academy_cairn import rated

analyzer = rated(peer_handle, agent=self)   # uses this agent's Cairn client
result = await analyzer.analyze(data)       # transparently scored, re-raised on failure
```

**Reading scores directly**, e.g. to route work or gate a workflow. The agent's
client is on `self.cairn` (present once the guard has provisioned it, or from the
first line if you use `CairnAgentMixin`):

```python
reading = await self.cairn.get_score(EntityRef(type="agent", external_id=peer_id))
if reading.confidence >= 0.3 and reading.composite_score < 0.4:
    ...  # low-trust peer — pick another
print(reading.profile_url)   # its page on cairnscore.ai
```

Every read carries a `profile_url` — the entity's page on cairnscore.ai (score
history, per-dimension breakdown, individual rating events).

## How it behaves

- **Fail-open, always.** Any Cairn error — network, timeout, 4xx/5xx, rate limit —
  degrades to a debug log; the guarded action and the peer call always proceed. A
  Cairn outage can never break an agent.
- **Non-blocking writes.** Ratings are enqueued locally (an append-only JSONL
  queue) and flushed in batches by a background task and on shutdown. Nothing on
  the action path waits on the network.
- **HPC / offline-friendly.** Set `CAIRN_OFFLINE=1` on a node with no outbound
  network: ratings accumulate on disk and drain later from a login node with
  `python -m academy_cairn.flush`.
- **Stable identity.** An agent rates and is rated as
  `agent://academy/{namespace}/{agent_name}`, so reputation accumulates across
  runs.
- **Off switch.** `CAIRN_ENABLED=0` makes the guard and `rated` no-ops.

## Configuration

Everything is read from `CAIRN_*` environment variables (via pydantic-settings):

| Variable | Default | Purpose |
|----------|---------|---------|
| `CAIRN_BASE_URL` | `https://api.cairnscore.ai` | Cairn API root |
| `CAIRN_NAMESPACE` | hostname | groups this host's agent identities |
| `CAIRN_ENABLED` | `true` | global off switch |
| `CAIRN_OFFLINE` | `false` | enqueue only; no network (drain later via the CLI) |
| `CAIRN_DEFAULT_WEIGHT` | `0.3` | weight of automated outcome ratings |
| `CAIRN_TIMEOUT_S` | `5` | per-request timeout |
| `CAIRN_FLUSH_INTERVAL_S` | `60` | background flush interval |
| `CAIRN_KEY_DIR` | `~/.cairn/academy/keys` | on-disk key store (mode 0600) |

## The optional mixin

The decorator provisions its client lazily and flushes on shutdown, so no base
class is required. If you'd rather wire it explicitly — client created eagerly on
startup, with a background flusher tuned for a long-lived agent — add
`CairnAgentMixin`:

```python
from academy_cairn import CairnAgentMixin

class MyAgent(CairnAgentMixin, Agent):
    ...   # self.cairn is created on startup and flushed on shutdown
```

## Examples

Runnable, self-contained demos that launch real Academy agents against a live
Cairn are in [`examples/`](examples/) — three escalating scenarios (trust
accumulates → the guard blocks a low-trust source → peer scoring), plus a
notebook. Start with:

```bash
CAIRN_NAMESPACE=demo uv run python examples/02_guard_blocks.py
```

## Status

Cairn is an early hosted proof-of-concept; this package targets its `/v1` API.
Design notes and the implementation plan live under
[`docs/superpowers/`](docs/superpowers/).
