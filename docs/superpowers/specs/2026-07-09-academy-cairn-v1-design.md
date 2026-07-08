# academy-cairn v1 — design spec (M0–M4)

Trust-aware Academy agents: check Cairn before acting on an external resource, rate
after, and score peer agents from ground-truth invocation outcomes. This spec covers
the complete installable `academy-cairn` package (milestones M0–M4). It supersedes the
exploratory `Cairn/growth/academy-cairn-design.md`, folding in the packaging and
architecture decisions settled during brainstorming.

**Repo:** this package lives standalone in the Cairn GitHub org (`academy-cairn`).
`academy-py` is a required dependency and is **not** modified by this work. Cairn API
contract: `Cairn/cairn-service/README.md` and `docs/integration.md`.

## Goals / non-goals

**Goals**

1. One-liner adoption for any Academy agent: reads with zero setup, writes with lazy key minting.
2. A guard decorator that composes with `@action`: pre-check score → policy (log/warn/block)
   → post-rate from an observable signal. No LLM required.
3. Peer-agent rating from Handle invocation outcomes — ground truth (did the peer answer,
   correctly, in time), not text analysis.
4. HPC-safe: fully async, fail-open, offline queue with batch flush for nodes without
   outbound network.

**Non-goals (v1)**

- No LLM-based rater (the cairn-score-skill pattern can be added later as an optional backend).
- No changes to Academy core; everything works via public seams (verified below).
- No blocking-by-default anywhere. Default policy is observe/log.
- No client-side re-implementation of Cairn's external-id normalization — the server
  normalizes on every read and write (`normalize_external_id`), so the client sends raw ids.
- **Out of scope for this spec:** M5 (Argus dogfood soak) and M6 (academy-extensions
  decision gate). Each becomes its own future spec in its own repo.

## Packaging decision (why standalone, not academy-extensions)

`academy-cairn` ships as a **standalone single package in the Cairn org**, depending on
`academy-py` (dependency direction Cairn→Academy; Academy never learns Cairn exists).
This is the most decoupled and most reversible starting point.

`academy-extensions` (the Academy org's first-party extensions repo, currently home to the
MCP plugin) is the likely **eventual** home for a thin glue layer — it is the blessed,
discoverable place Academy users look for "adjacent optional functionality." It is a bad
**starting** point, for three grounded reasons:

1. **Single-package, all-mandatory-deps model.** `academy-extensions` publishes one package
   (`academy-extensions` 0.1.0) with a single release train and no per-integration extras —
   `mcp[cli]` is a hard runtime dependency for everyone. Adding Cairn there would force
   `httpx` + the Cairn client onto every MCP user (and `mcp[cli]` onto every Cairn user), and
   couple our pre-1.0 API churn to their release cadence.
2. **Cross-org ownership inversion.** It is the `academy-agents` org's repo (their CI, review
   bar, release authority). Hosting Cairn's core trust logic there makes us a guest in someone
   else's repo for our own product feature, and asks the Academy org to take a runtime
   dependency on our SaaS's API stability.
3. **Premature channel.** The extensions repo is itself young (freshly at 0.1.0). Betting
   distribution on it before we have soak evidence stacks two unproven things.

The move standalone→extensions is cheap later (relocate a thin layer, add a docs cross-ref);
extensions→standalone or core→anything would be a breaking change for adopters. We start at
the reversible point and earn the move up with M5 evidence — that is what the future M6
decision gate is for.

## Verified integration seams (Academy source, `academy-agents/academy`)

Checked against the code — do not re-derive:

- `academy/agent.py`: `@action` requires a coroutine and marks it via
  `method._agent_method_type = 'action'` (and `_action_method_context`). A decorator applied
  **below** `@action` (closer to the `def`) wraps first; `@action` then marks the wrapper. So
  `@action` over `@cairn_guarded` composes cleanly as long as the wrapper is a coroutine and
  uses `functools.wraps`. (`agent.py:216` sets the marker; the `action` overloads begin at
  `agent.py:114`.)
- `academy/agent.py`: `Agent.agent_on_startup()` / `agent_on_shutdown()` lifecycle hooks
  (`agent.py:659` / `agent.py:673`) — init client / start flusher / flush queue here.
- `academy/handle.py`: **every** remote invocation funnels through
  `Handle.action(name, /, *args, **kwargs)` (attribute calls go via `__getattr__` →
  `remote_method_call` → `self.action(...)`). It raises `AgentTerminatedError` or re-raises the
  action's exception. This is the single choke point for peer rating. Handles are serialized via
  `__reduce__`/`__setstate__`, so **subclassing is fragile across serialization** — use a
  non-serialized local proxy instead (M4).
- `academy/identifier.py`: `AgentId(uid: UUID, name: str | None)`. Names are optional and not
  unique; uids are unique but ephemeral per launch.

## Cairn contract facts the implementation must respect

- Write endpoints: `POST /v1/scores` (single), `POST /v1/scores/batch` (≤100 events, atomic,
  1 rate-limit token per batch). Reads are unauthenticated.
- `weight ∈ (0,1]`; canonical dimensions: `accuracy`, `latency`, `cost`, `reliability`,
  `safety`, `token_efficiency`, `context_efficiency`.
- Key minting: `POST /v1/keys`, plaintext returned once, `reviewer_external_id` **claim-once**.
  Reserved prefixes `agent://cairn-` and `agent://anthropic/` are rejected.
- Unknown entity reads return `composite_score: 0.5, confidence: 0.0` — the guard must treat
  this as "no data", never as "bad".
- Per-key write limit 50 rps sustained / 100 burst — a batch flush is well within this.

## Package layout

```
academy-cairn/
├── pyproject.toml          # hatchling; deps: httpx, pydantic, pydantic-settings, academy-py (required)
├── README.md
├── src/academy_cairn/
│   ├── __init__.py         # public API: CairnClient, cairn_guarded, rated, CairnConfig,
│   │                       #             TrustPolicy, CairnAgentMixin, EntityRef
│   ├── config.py           # CairnConfig (pydantic-settings, env prefix CAIRN_)
│   ├── client.py           # CairnClient: async httpx wrapper over /v1 (owns its transport)
│   ├── identity.py         # reviewer identity + claim-once key store
│   ├── queue.py            # JSONL offline queue + batch flusher + `python -m academy_cairn.flush`
│   ├── guard.py            # @cairn_guarded decorator + TrustPolicy
│   ├── rater.py            # heuristic outcome→rating mapping
│   ├── peers.py            # rated(handle) proxy for peer-agent scoring
│   ├── mixin.py            # CairnAgentMixin (lifecycle: init client, start flusher, flush)
│   └── entity.py           # EntityRef(type, external_id) + agent-id → entity helpers
└── tests/
    ├── unit/               # httpx.MockTransport; no network
    └── integration/        # skip-guarded on CAIRN_TEST_URL (local cairn-service docker-compose)
```

## Locked decisions

1. **Reviewer identity** = `agent://academy/{namespace}/{agent_name}`. `namespace` from
   `CAIRN_ACADEMY_NAMESPACE` (default: hostname); `agent_name` from `AgentId.name`, falling
   back to `anon-{uid[:8]}` when unnamed. Rationale: stable names accumulate rater reputation
   across relaunches; uid-only identities fragment it. **Claim-once collision handling:** if
   minting fails because the id is claimed and no local key exists, retry once with `-{uid[:8]}`
   suffix and log a warning. Key files at `~/.cairn/academy/keys/{host}/{identity-slug}.key`,
   mode 0600 — deliberately *not* the cairn-score-skill's `~/.cairn/keys/<host>.key`, so a
   human's skill identity and their agents' identities never collide.
2. **Entity id for a peer agent** = the reviewer identity formula applied to the *handle's*
   `agent_id`. Same formula both directions keeps profiles unified.
3. **Fail-open everywhere.** Any Cairn error (network, 5xx, rate limit) degrades to a debug
   log; the guarded action always runs, the Handle call always proceeds. Enforced by test
   (M2/M4 acceptance).
4. **Default policy is `log`.** `block` exists but must be explicitly configured per-guard;
   blocking requires `confidence ≥ min_confidence` — never block on no-data.
5. **Writes always go through the queue** (even online): enqueue is sync-fast and non-blocking
   on the action path; a background flusher drains via `/v1/scores/batch`. One code path,
   offline-safe by construction.
6. **Heuristic rater weights are low** (default `weight=0.3`) — automated outcome signal
   shouldn't drown organic evidence-rich ratings. Configurable.

### Decisions settled during brainstorming (this spec)

7. **Per-agent HTTP transport.** Each `CairnClient` owns its own `httpx.AsyncClient`, opened in
   `agent_on_startup` and closed in `agent_on_shutdown`. Simple and self-contained; `CairnClient`
   remains the seam, so a process-wide shared transport can be introduced later without changing
   callers. (Rejected for v1: shared reference-counted process transport — deferred as an
   optimization.)
8. **Rating `context` field** = `"general"` for v1. Revisit if cross-domain contamination shows
   up (a per-domain context is a one-line change at the mixin).
9. **Latency→score mapping** in `rater.py` = fixed thresholds `<1s ⇒ 1.0`, `<5s ⇒ 0.7`,
   `else ⇒ 0.4`. Documented as tunable; per-entity baselines are a future refinement.
10. **`discover()` convenience on the mixin** is included (`self.cairn.discover(...)` is already
    on the client; the mixin exposes it directly).

## Configuration (`CairnConfig`, env prefix `CAIRN_`)

| field | default | notes |
|-------|---------|-------|
| `base_url` | `https://api.cairnscore.ai` | Cairn API root |
| `namespace` | hostname | reviewer identity namespace |
| `key_dir` | `~/.cairn/academy/keys` | claim-once key store root |
| `default_weight` | `0.3` | heuristic rating weight |
| `timeout_s` | `5` | per-request httpx timeout |
| `enabled` | `true` | global kill-switch (false ⇒ mixin/guard are no-ops) |
| `flush_interval_s` | `60` | background flusher interval |
| `offline` | `false` | `CAIRN_OFFLINE=1` ⇒ enqueue only, zero network |

## Milestones

### M0 — scaffold

`pyproject.toml` (hatchling, py ≥3.10 to match Academy), ruff + mypy strict config mirroring
cairn-service's, empty modules.
**Acceptance:** `uv sync --extra dev && uv run pytest` green on an empty test.

### M1 — `CairnClient` + identity + config

`config.py`: `CairnConfig` as tabled above.

`client.py`: async methods `get_score(ref)`, `get_profile(ref)`, `discover(query, k)`,
`rank(...)`, `read_batch(refs)`, `submit(event)`, `submit_batch(events)`. Reads need no key.
First write triggers lazy mint via `identity.py` (claim-once handling per locked decision 1).
Each `CairnClient` owns a single `httpx.AsyncClient`; explicit `aclose()` (locked decision 7).

**Acceptance:** unit tests with `httpx.MockTransport` cover mint-once, mint-collision-retry,
read of unknown entity returning `(0.5, 0.0)`, batch chunking at 100; integration test
(skip-guarded on `CAIRN_TEST_URL`) does mint → write → read against local cairn-service.

### M2 — `@cairn_guarded`

```python
class TrustPolicy(BaseModel):
    min_score: float = 0.4
    min_confidence: float = 0.3      # below this ⇒ "no data" ⇒ always proceed
    on_low: Literal['log', 'warn', 'block'] = 'log'

@action
@cairn_guarded(type='data_source', id_from='url', policy=TrustPolicy(), rate=True)
async def fetch_dataset(self, url: str) -> bytes: ...
```

- `id_from`: str (parameter name, resolved via `inspect.signature`) or
  `Callable[..., EntityRef]` for computed ids.
- Pre: read score → apply policy. `block` raises `CairnTrustError(ref, reading)`.
- Post (when `rate=True`): call `rater.py` — success ⇒ score 0.75 with
  `dimensions={'reliability': 1.0, 'latency': f(elapsed)}`, `metrics={'latency_ms': ...}`;
  exception ⇒ score 0.2, `failure_modes=[exc_class_name]`, then re-raise. Templated rationale
  ≤1 sentence; **never** interpolate argument values other than the entity id (secrets
  discipline).
- The guard finds the client on `self` (`self.cairn`, provided by `CairnAgentMixin`); if
  absent, the guard is a no-op (fail-open).

**Acceptance:** decorator composes under `@action` (assert `_agent_method_type == 'action'`
on the wrapped method); block-path raises only when confidence ≥ threshold; Cairn outage
(transport error injected) never prevents the action; exception path re-raises the original
exception *and* enqueues a low rating.

### M3 — offline queue + flusher

`queue.py`: append-only JSONL at `~/.cairn/academy/queue/{identity-slug}.jsonl` (one file per
reviewer, no cross-process interleaving), `enqueue(event)` non-async and O(1); `flush()` drains
in ≤100-event batches, removes only acknowledged lines (rewrite-on-success), tolerates corrupt
lines (skip + warn). Background task started by the mixin (`agent_on_startup`, interval
`CAIRN_FLUSH_INTERVAL_S`, default 60) and a final flush in `agent_on_shutdown`. `CAIRN_OFFLINE=1`
disables the network entirely (enqueue only) — the HPC compute-node mode; flush later from a
login node via CLI: `python -m academy_cairn.flush`.

**Acceptance:** kill-during-flush loses no events (idempotent re-flush ok — server dedup isn't
available, so at-least-once is accepted and documented); `CAIRN_OFFLINE=1` produces zero network
calls (assert via MockTransport call count); CLI flush drains a fixture queue against local
cairn-service.

### M4 — peer rating: `rated(handle)`

A local, non-serialized proxy (composition, not subclassing — Handles have custom `__reduce__`):

```python
analyzer = rated(analyzer_handle, cairn=self.cairn)   # in the receiving agent
result = await analyzer.analyze(data)                  # rated transparently
```

`peers.py::RatedHandle` implements `__getattr__` delegating to the wrapped handle but routing
calls through the wrapped `action()`: time the call; success ⇒ enqueue rating on
`reliability`/`latency` for `agent://academy/{ns}/{peer}`; `AgentTerminatedError` or action
exception ⇒ low `reliability` with the exception class as failure mode; re-raise always.
`ping()` results may also feed `latency`. Non-invocation attributes (`agent_id`, `shutdown`, …)
pass through unwrapped. If a `RatedHandle` is accidentally serialized, it degrades to the plain
handle (`__reduce__` returns the inner handle) — rating is a local concern.

**Acceptance:** transparent delegation (a `ProxyHandle`-based unit test calls an action and gets
the result); success and failure both enqueue exactly one event with correct entity id;
serialization round-trip yields a plain working handle.

## Future work (separate specs, not this repo's package build)

- **M5 — dogfood: Argus.** In `academy-agents/argus` (separate branch/PR): LogWatcher rates its
  log sources (`data_source`), TriageAgent rates the Anthropic endpoint (`capability`),
  AlertAgent rates the Slack webhook (`capability`), inter-agent Handles wrapped with `rated(...)`.
  2-week soak against prod Cairn under `agent://academy/argus/*` identities. Acceptance: events
  visible via `GET /v1/profile`; a deliberately broken log path shows as decayed low
  `reliability`; short writeup appended.
- **M6 — extensions decision gate.** Given M5 evidence and a stabilized client API, decide:
  petition `academy-extensions` to adopt a thin glue layer (which requires them to add
  per-integration optional extras), *or* stay standalone with a docs cross-reference. Low-cost
  early move: open an issue on `academy-extensions` proposing per-integration extras, to learn
  whether that channel is viable at all.

## Testing & verification strategy

- **Unit:** everything through `httpx.MockTransport`; no network, no Academy runtime needed
  except `ProxyHandle` (importable, in-process, ideal for M4 tests).
- **Integration:** `cairn-service`'s `make up` (docker-compose Postgres + API) is the fixture
  backend; tests skip unless `CAIRN_TEST_URL` is set. Mirrors cairn-service's own local-dev flow.
- **End-to-end:** deferred to M5 (out of scope here).
- Every milestone's acceptance criteria are executable — encode them as tests, not prose.
