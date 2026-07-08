# academy-cairn v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the installable `academy-cairn` package so any Academy agent can check Cairn before acting on an external resource, rate the outcome, and score peer agents — fail-open, async, offline-safe, no LLM.

**Architecture:** A per-agent `CairnClient` owns its own `httpx.AsyncClient` and its own append-only JSONL write queue. A `@cairn_guarded` decorator composes under Academy's `@action` to pre-check trust and post-rate from the observable outcome. A `rated(handle)` proxy scores peer agents from `Handle.action` outcomes. `CairnAgentMixin` wires the client into the agent lifecycle (`agent_on_startup`/`agent_on_shutdown`) and runs a background batch flusher.

**Tech Stack:** Python ≥3.10, `httpx` (async), `pydantic` v2, `pydantic-settings`, `academy-py` (required dep). Hatchling build. Tests: `pytest`, `pytest-asyncio`, `httpx.MockTransport` (no network); integration tests skip-guarded on `CAIRN_TEST_URL`.

## Global Constraints

Every task's requirements implicitly include this section.

- **Python floor:** `requires-python = ">=3.10"` (matches Academy).
- **Package:** distribution name `academy-cairn`; import package `academy_cairn`; `src/` layout; build backend `hatchling`.
- **Runtime deps (all required):** `httpx`, `pydantic>=2,<3`, `pydantic-settings`, `academy-py`.
- **Lint/type:** `ruff` + `mypy` strict; all public functions fully type-annotated.
- **Config env prefix:** `CAIRN_` (pydantic-settings).
- **Cairn API:** base default `https://api.cairnscore.ai`. Reads (`GET /v1/score`, `POST /v1/score/batch`, `GET /v1/profile`, `POST /v1/discover`, `POST /v1/rank`) are **unauthenticated**. Writes (`POST /v1/scores`, `POST /v1/scores/batch`) require header `X-Api-Key`. Mint: `POST /v1/keys` → `{"api_key", ...}`; reserved prefixes return 422; duplicate `reviewer_external_id` returns 409. Error envelope: `{"error": {"code", "message"}}`.
- **Fail-open everywhere:** any Cairn error (transport, 4xx/5xx, timeout) degrades to a debug log; the guarded action and the Handle call always proceed.
- **Default policy is `log`.** `block` requires `confidence >= min_confidence` — never block on no-data.
- **All writes go through the queue** (even online). `enqueue()` is sync and O(1); a background flusher drains via `POST /v1/scores/batch`.
- **Heuristic rating weight default `0.3`.** Batch size cap: **100 events**.
- **Reviewer identity:** `agent://academy/{namespace}/{agent_name}`. Keys stored at `~/.cairn/academy/keys/{host}/{slug}.key`, mode `0600`.
- **Canonical dimensions:** `accuracy`, `latency`, `cost`, `reliability`, `safety`, `token_efficiency`, `context_efficiency` (all higher-is-better).
- **`failure_modes`/`task_tags`:** arrays of snake_case ids matching `^[a-z][a-z0-9_]{0,63}$`, ≤10 items.
- **Secrets discipline:** never interpolate any argument value except the entity id into a `rationale`/`task` string.

**Build order (dependency graph — refines spec milestone order so the guard can enqueue without a throwaway path):**
scaffold → config → entity types → identity/keystore → client reads → client writes+mint → **queue (before guard)** → rater → guard → mixin → peers.

---

### Task 1: Project scaffold (M0)

**Files:**
- Create: `pyproject.toml`, `src/academy_cairn/__init__.py`, `src/academy_cairn/py.typed`, `tests/unit/__init__.py`, `tests/unit/test_smoke.py`
- Create empty modules: `src/academy_cairn/{config,entity,identity,client,queue,rater,guard,mixin,peers}.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an importable `academy_cairn` package and a green `pytest`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "academy-cairn"
version = "0.1.0"
description = "Trust-aware Academy agents backed by Cairn reputation scores."
readme = "README.md"
requires-python = ">=3.10"
license = "MIT"
dependencies = [
    "httpx",
    "pydantic>=2,<3",
    "pydantic-settings",
    "academy-py",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio>=1.1", "pytest-cov", "mypy", "ruff>=0.2.0"]

[tool.hatch.build.targets.wheel]
packages = ["src/academy_cairn"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.mypy]
strict = true
python_version = "3.10"

[tool.ruff]
line-length = 88
```

- [ ] **Step 2: Create `README.md` (one line) and empty modules**

`README.md`:
```markdown
# academy-cairn

Trust-aware Academy agents backed by Cairn. See `docs/superpowers/specs/`.
```

Create each of `src/academy_cairn/{config,entity,identity,client,queue,rater,guard,mixin,peers}.py` containing only a module docstring, e.g. `"""Cairn client."""`. Create empty `src/academy_cairn/py.typed`. Put `"""academy-cairn public API."""` in `__init__.py`.

- [ ] **Step 3: Write the smoke test**

```python
# tests/unit/test_smoke.py
import academy_cairn


def test_package_imports():
    assert academy_cairn is not None
```

- [ ] **Step 4: Sync and run**

Run: `uv venv && uv pip install -e '.[dev]' && uv run pytest -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: scaffold academy-cairn package (M0)"
```

---

### Task 2: `CairnConfig` (M1)

**Files:**
- Modify: `src/academy_cairn/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CairnConfig` (pydantic-settings `BaseSettings`, env prefix `CAIRN_`) with fields `base_url: str`, `namespace: str`, `key_dir: Path`, `default_weight: float`, `timeout_s: float`, `enabled: bool`, `flush_interval_s: float`, `offline: bool`. `namespace` defaults to `socket.gethostname()`; `key_dir` defaults to `~/.cairn/academy/keys`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config.py
from pathlib import Path
from academy_cairn.config import CairnConfig


def test_defaults():
    cfg = CairnConfig()
    assert cfg.base_url == "https://api.cairnscore.ai"
    assert cfg.default_weight == 0.3
    assert cfg.timeout_s == 5.0
    assert cfg.enabled is True
    assert cfg.offline is False
    assert cfg.flush_interval_s == 60.0
    assert cfg.namespace  # non-empty (hostname)
    assert cfg.key_dir.name == "keys"


def test_env_override(monkeypatch):
    monkeypatch.setenv("CAIRN_NAMESPACE", "argus")
    monkeypatch.setenv("CAIRN_OFFLINE", "1")
    monkeypatch.setenv("CAIRN_DEFAULT_WEIGHT", "0.5")
    cfg = CairnConfig()
    assert cfg.namespace == "argus"
    assert cfg.offline is True
    assert cfg.default_weight == 0.5
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_config.py -q`
Expected: FAIL (`ImportError: cannot import name 'CairnConfig'`).

- [ ] **Step 3: Implement**

```python
# src/academy_cairn/config.py
"""Configuration for academy-cairn (env prefix CAIRN_)."""
from __future__ import annotations

import socket
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_namespace() -> str:
    return socket.gethostname() or "localhost"


def _default_key_dir() -> Path:
    return Path.home() / ".cairn" / "academy" / "keys"


class CairnConfig(BaseSettings):
    """Runtime configuration, read from CAIRN_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="CAIRN_", extra="ignore")

    base_url: str = "https://api.cairnscore.ai"
    namespace: str = Field(default_factory=_default_namespace)
    key_dir: Path = Field(default_factory=_default_key_dir)
    default_weight: float = 0.3
    timeout_s: float = 5.0
    enabled: bool = True
    flush_interval_s: float = 60.0
    offline: bool = False
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_config.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/academy_cairn/config.py tests/unit/test_config.py
git commit -m "feat: CairnConfig with CAIRN_ env settings (M1)"
```

---

### Task 3: Core data types — `EntityRef`, `Reading`, `ScoreEvent` (M1)

**Files:**
- Modify: `src/academy_cairn/entity.py`
- Test: `tests/unit/test_entity.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `EntityType = Literal["data_source", "capability", "agent"]`
  - `EntityRef(BaseModel)`: `type: EntityType`, `external_id: str`.
  - `Reading(BaseModel)`: `composite_score: float`, `confidence: float`, `last_updated: str | None = None`. Classmethod `Reading.no_data() -> Reading` returns `(0.5, 0.0, None)`.
  - `ScoreEvent(BaseModel)`: `reviewee: EntityRef`, `score: float`, `context: str = "general"`, plus optional `weight, task, dimensions, rationale, failure_modes, metrics, observed_at`. Method `to_payload() -> dict` (drops `None`, nests `reviewee`).
  - `agent_entity(namespace: str, agent_name: str) -> EntityRef` → `EntityRef("agent", f"agent://academy/{namespace}/{agent_name}")`.
  - `snake_case(name: str) -> str` → converts e.g. `TimeoutError` → `timeout_error`, clamped to `^[a-z][a-z0-9_]{0,63}$`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_entity.py
from academy_cairn.entity import (
    EntityRef, Reading, ScoreEvent, agent_entity, snake_case,
)


def test_reading_no_data():
    r = Reading.no_data()
    assert (r.composite_score, r.confidence, r.last_updated) == (0.5, 0.0, None)


def test_score_event_payload_drops_none():
    ev = ScoreEvent(
        reviewee=EntityRef(type="data_source", external_id="https://a.example/v1"),
        score=0.75,
        dimensions={"reliability": 1.0},
    )
    payload = ev.to_payload()
    assert payload["reviewee"] == {"type": "data_source", "external_id": "https://a.example/v1"}
    assert payload["score"] == 0.75
    assert payload["context"] == "general"
    assert payload["dimensions"] == {"reliability": 1.0}
    assert "rationale" not in payload  # None fields dropped
    assert "weight" not in payload


def test_agent_entity_formula():
    ref = agent_entity("argus", "triage")
    assert ref.type == "agent"
    assert ref.external_id == "agent://academy/argus/triage"


def test_snake_case():
    assert snake_case("TimeoutError") == "timeout_error"
    assert snake_case("HTTPError") == "http_error"
    assert snake_case("ValueError") == "value_error"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_entity.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
# src/academy_cairn/entity.py
"""Core data types: entity refs, readings, and score events."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

EntityType = Literal["data_source", "capability", "agent"]


class EntityRef(BaseModel):
    type: EntityType
    external_id: str


class Reading(BaseModel):
    composite_score: float
    confidence: float
    last_updated: str | None = None

    @classmethod
    def no_data(cls) -> "Reading":
        return cls(composite_score=0.5, confidence=0.0, last_updated=None)


class ScoreEvent(BaseModel):
    reviewee: EntityRef
    score: float
    context: str = "general"
    weight: float | None = None
    task: str | None = None
    dimensions: dict[str, float] | None = None
    rationale: str | None = None
    failure_modes: list[str] | None = None
    metrics: dict[str, float] | None = None
    observed_at: str | None = None

    def to_payload(self) -> dict:
        return self.model_dump(exclude_none=True)


def agent_entity(namespace: str, agent_name: str) -> EntityRef:
    return EntityRef(type="agent", external_id=f"agent://academy/{namespace}/{agent_name}")


_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def snake_case(name: str) -> str:
    s = _CAMEL.sub("_", name).lower()
    s = re.sub(r"[^a-z0-9_]", "_", s).strip("_")
    if not s or not s[0].isalpha():
        s = f"e_{s}" if s else "unknown"
    return s[:64]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_entity.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/academy_cairn/entity.py tests/unit/test_entity.py
git commit -m "feat: core data types EntityRef/Reading/ScoreEvent (M1)"
```

---

### Task 4: Reviewer identity + key store (M1)

**Files:**
- Modify: `src/academy_cairn/identity.py`
- Test: `tests/unit/test_identity.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `reviewer_external_id(namespace: str, agent_name: str) -> str` → `agent://academy/{namespace}/{agent_name}`.
  - `agent_name_from(name: str | None, uid: str) -> str` → `name` or `anon-{uid[:8]}`.
  - `identity_slug(reviewer_id: str) -> str` → filesystem-safe slug (e.g. `academy_argus_triage`).
  - `KeyStore(key_dir: Path, host: str)` with `load(slug: str) -> str | None` and `save(slug: str, key: str) -> None` (creates parents, writes mode `0600`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_identity.py
import stat
from academy_cairn.identity import (
    reviewer_external_id, agent_name_from, identity_slug, KeyStore,
)


def test_reviewer_external_id():
    assert reviewer_external_id("argus", "triage") == "agent://academy/argus/triage"


def test_agent_name_fallback():
    assert agent_name_from("triage", "abcd1234ffff") == "triage"
    assert agent_name_from(None, "abcd1234ffff") == "anon-abcd1234"


def test_identity_slug():
    assert identity_slug("agent://academy/argus/triage") == "academy_argus_triage"


def test_keystore_roundtrip_and_perms(tmp_path):
    store = KeyStore(tmp_path, host="node01")
    assert store.load("academy_argus_triage") is None
    store.save("academy_argus_triage", "tg_secret")
    assert store.load("academy_argus_triage") == "tg_secret"
    key_file = tmp_path / "node01" / "academy_argus_triage.key"
    mode = stat.S_IMODE(key_file.stat().st_mode)
    assert mode == 0o600
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_identity.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
# src/academy_cairn/identity.py
"""Reviewer identity strings and the on-disk claim-once key store."""
from __future__ import annotations

import re
from pathlib import Path


def reviewer_external_id(namespace: str, agent_name: str) -> str:
    return f"agent://academy/{namespace}/{agent_name}"


def agent_name_from(name: str | None, uid: str) -> str:
    return name if name else f"anon-{uid[:8]}"


def identity_slug(reviewer_id: str) -> str:
    body = reviewer_id.replace("agent://", "")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", body).strip("_").lower()
    return slug


class KeyStore:
    """Persists minted API keys, one file per reviewer identity, mode 0600."""

    def __init__(self, key_dir: Path, host: str) -> None:
        self._dir = Path(key_dir) / host

    def _path(self, slug: str) -> Path:
        return self._dir / f"{slug}.key"

    def load(self, slug: str) -> str | None:
        path = self._path(slug)
        if not path.exists():
            return None
        return path.read_text().strip() or None

    def save(self, slug: str, key: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path(slug)
        path.write_text(key)
        path.chmod(0o600)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_identity.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/academy_cairn/identity.py tests/unit/test_identity.py
git commit -m "feat: reviewer identity + claim-once key store (M1)"
```

---

### Task 5: `CairnClient` reads (M1)

**Files:**
- Modify: `src/academy_cairn/client.py`
- Test: `tests/unit/test_client_reads.py`

**Interfaces:**
- Consumes: `CairnConfig`, `EntityRef`, `Reading` (Tasks 2–3).
- Produces: `CairnClient(config, *, reviewer_id, uid, key_store, transport=None)`. Async read methods:
  - `get_score(ref: EntityRef) -> Reading`
  - `read_batch(refs: list[EntityRef]) -> dict[str, Reading]` (keyed by `external_id`)
  - `get_profile(ref: EntityRef) -> dict`
  - `discover(query: str, k: int = 5) -> list[dict]`
  - `rank(capability_tag: str, rank_by: str, k: int = 5) -> dict`
  - `aclose() -> None`
  - All reads are **fail-open**: on any exception or non-2xx they log at debug and return no-data (`Reading.no_data()` / `{}` / `[]`). In `config.offline` mode, reads short-circuit to no-data with zero network calls.
  - `transport` param lets tests inject `httpx.MockTransport`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_client_reads.py
import httpx
import pytest
from academy_cairn.config import CairnConfig
from academy_cairn.client import CairnClient
from academy_cairn.entity import EntityRef


def make_client(handler, **cfg):
    config = CairnConfig(**cfg)
    return CairnClient(
        config,
        reviewer_id="agent://academy/test/agent",
        uid="uid00000000",
        key_store=None,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_get_score_parses_reading():
    def handler(req):
        assert req.url.path == "/v1/score"
        return httpx.Response(200, json={"composite_score": 0.82, "confidence": 0.6, "last_updated": "x"})
    client = make_client(handler)
    r = await client.get_score(EntityRef(type="data_source", external_id="https://a/v1"))
    assert (r.composite_score, r.confidence) == (0.82, 0.6)
    await client.aclose()


@pytest.mark.asyncio
async def test_unknown_entity_is_no_data():
    def handler(req):
        return httpx.Response(200, json={"composite_score": 0.5, "confidence": 0.0, "last_updated": None})
    client = make_client(handler)
    r = await client.get_score(EntityRef(type="capability", external_id="mcp://x"))
    assert (r.composite_score, r.confidence) == (0.5, 0.0)
    await client.aclose()


@pytest.mark.asyncio
async def test_reads_fail_open_on_error():
    def handler(req):
        raise httpx.ConnectError("boom")
    client = make_client(handler)
    r = await client.get_score(EntityRef(type="data_source", external_id="https://a/v1"))
    assert (r.composite_score, r.confidence) == (0.5, 0.0)  # degrades, never raises
    await client.aclose()


@pytest.mark.asyncio
async def test_offline_reads_make_no_network_calls():
    calls = {"n": 0}
    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, json={"composite_score": 0.9, "confidence": 0.9})
    client = make_client(handler, offline=True)
    r = await client.get_score(EntityRef(type="data_source", external_id="https://a/v1"))
    assert (r.composite_score, r.confidence) == (0.5, 0.0)
    assert calls["n"] == 0
    await client.aclose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_client_reads.py -q`
Expected: FAIL (ImportError / attribute errors).

- [ ] **Step 3: Implement**

```python
# src/academy_cairn/client.py
"""Async Cairn API client (one httpx transport per agent)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import CairnConfig
from .entity import EntityRef, Reading

logger = logging.getLogger("academy_cairn")


class CairnClient:
    def __init__(
        self,
        config: CairnConfig,
        *,
        reviewer_id: str,
        uid: str,
        key_store: Any,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self._reviewer_id = reviewer_id
        self._uid = uid
        self._keys = key_store
        self._api_key: str | None = None
        self._http = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout_s,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_score(self, ref: EntityRef) -> Reading:
        if self.config.offline:
            return Reading.no_data()
        try:
            resp = await self._http.get(
                "/v1/score",
                params={"type": ref.type, "external_id": ref.external_id},
            )
            resp.raise_for_status()
            return Reading.model_validate(resp.json())
        except Exception as exc:  # fail-open
            logger.debug("cairn get_score failed for %s: %s", ref.external_id, exc)
            return Reading.no_data()

    async def read_batch(self, refs: list[EntityRef]) -> dict[str, Reading]:
        if self.config.offline or not refs:
            return {r.external_id: Reading.no_data() for r in refs}
        try:
            resp = await self._http.post(
                "/v1/score/batch",
                json={"refs": [r.model_dump() for r in refs]},
            )
            resp.raise_for_status()
            return {
                item["external_id"]: Reading.model_validate(item)
                for item in resp.json()
            }
        except Exception as exc:  # fail-open
            logger.debug("cairn read_batch failed: %s", exc)
            return {r.external_id: Reading.no_data() for r in refs}

    async def get_profile(self, ref: EntityRef) -> dict:
        if self.config.offline:
            return {}
        try:
            resp = await self._http.get(
                "/v1/profile",
                params={"type": ref.type, "external_id": ref.external_id},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # fail-open
            logger.debug("cairn get_profile failed: %s", exc)
            return {}

    async def discover(self, query: str, k: int = 5) -> list[dict]:
        if self.config.offline:
            return []
        try:
            resp = await self._http.post("/v1/discover", json={"query": query, "k": k})
            resp.raise_for_status()
            return resp.json().get("results", [])
        except Exception as exc:  # fail-open
            logger.debug("cairn discover failed: %s", exc)
            return []

    async def rank(self, capability_tag: str, rank_by: str, k: int = 5) -> dict:
        if self.config.offline:
            return {}
        try:
            resp = await self._http.post(
                "/v1/rank",
                json={"capability_tag": capability_tag, "rank_by": rank_by, "k": k},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # fail-open
            logger.debug("cairn rank failed: %s", exc)
            return {}
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_client_reads.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/academy_cairn/client.py tests/unit/test_client_reads.py
git commit -m "feat: CairnClient read methods, fail-open + offline (M1)"
```

---

### Task 6: `CairnClient` writes + lazy key mint (M1)

**Files:**
- Modify: `src/academy_cairn/client.py`
- Test: `tests/unit/test_client_writes.py`

**Interfaces:**
- Consumes: `KeyStore` (Task 4), `ScoreEvent`, `identity_slug` (Tasks 3–4).
- Produces, on `CairnClient`:
  - `async _ensure_key() -> str | None`: returns cached key; else `KeyStore.load(slug)`; else mint via `POST /v1/keys`. On **409** with no local key, retry once with `reviewer_id + "-" + uid[:8]` (updates `self._reviewer_id`, logs warning). On other errors returns `None` (fail-open — writes are dropped, not raised).
  - `async submit(event: ScoreEvent) -> None`: `_ensure_key`, then `POST /v1/scores` with `X-Api-Key`. Fail-open.
  - `async submit_batch(events: list[ScoreEvent]) -> None`: chunks into ≤100, `POST /v1/scores/batch` per chunk. Fail-open. No-op if `offline`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_client_writes.py
import httpx
import pytest
from academy_cairn.config import CairnConfig
from academy_cairn.client import CairnClient
from academy_cairn.identity import KeyStore
from academy_cairn.entity import EntityRef, ScoreEvent


def _event(i=0):
    return ScoreEvent(reviewee=EntityRef(type="data_source", external_id=f"https://a/{i}"), score=0.75)


def make_client(handler, tmp_path, reviewer="agent://academy/test/agent"):
    return CairnClient(
        CairnConfig(),
        reviewer_id=reviewer,
        uid="uid00000000",
        key_store=KeyStore(tmp_path, host="node01"),
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_mint_once_then_cached(tmp_path):
    mints = {"n": 0}
    def handler(req):
        if req.url.path == "/v1/keys":
            mints["n"] += 1
            return httpx.Response(200, json={"api_key": "tg_minted"})
        return httpx.Response(200, json={"count": 1, "reviewees": []})
    client = make_client(handler, tmp_path)
    await client.submit(_event())
    await client.submit(_event())
    assert mints["n"] == 1  # minted once, then cached
    await client.aclose()


@pytest.mark.asyncio
async def test_mint_collision_retries_with_suffix(tmp_path):
    seen = []
    def handler(req):
        if req.url.path == "/v1/keys":
            body = req.read().decode()
            seen.append(body)
            if len(seen) == 1:
                return httpx.Response(409, json={"error": {"code": "conflict", "message": "claimed"}})
            return httpx.Response(200, json={"api_key": "tg_minted"})
        return httpx.Response(200, json={"count": 1, "reviewees": []})
    client = make_client(handler, tmp_path)
    await client.submit(_event())
    assert "agent://academy/test/agent" in seen[0]
    assert "agent://academy/test/agent-uid00000" in seen[1]  # -uid[:8]
    await client.aclose()


@pytest.mark.asyncio
async def test_submit_batch_chunks_at_100(tmp_path):
    chunks = []
    def handler(req):
        if req.url.path == "/v1/keys":
            return httpx.Response(200, json={"api_key": "tg_minted"})
        chunks.append(len(req.read().decode().split('"reviewee"')) - 1)
        return httpx.Response(200, json={"count": 0, "reviewees": []})
    client = make_client(handler, tmp_path)
    await client.submit_batch([_event(i) for i in range(150)])
    assert chunks == [100, 50]
    await client.aclose()


@pytest.mark.asyncio
async def test_writes_fail_open(tmp_path):
    def handler(req):
        raise httpx.ConnectError("down")
    client = make_client(handler, tmp_path)
    await client.submit(_event())  # must not raise
    await client.aclose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_client_writes.py -q`
Expected: FAIL (no `submit`/`_ensure_key`).

- [ ] **Step 3: Implement (append to `client.py`)**

Add imports at top: `from .entity import ScoreEvent` and `from .identity import identity_slug`. Then add these methods to `CairnClient`:

```python
    async def _mint(self, reviewer_id: str) -> httpx.Response:
        return await self._http.post("/v1/keys", json={"reviewer_external_id": reviewer_id})

    async def _ensure_key(self) -> str | None:
        if self._api_key is not None:
            return self._api_key
        slug = identity_slug(self._reviewer_id)
        if self._keys is not None:
            cached = self._keys.load(slug)
            if cached:
                self._api_key = cached
                return cached
        try:
            resp = await self._mint(self._reviewer_id)
            if resp.status_code == 409:
                self._reviewer_id = f"{self._reviewer_id}-{self._uid[:8]}"
                logger.warning("cairn identity claimed; retrying as %s", self._reviewer_id)
                slug = identity_slug(self._reviewer_id)
                resp = await self._mint(self._reviewer_id)
            resp.raise_for_status()
            key = resp.json()["api_key"]
            self._api_key = key
            if self._keys is not None:
                self._keys.save(slug, key)
            return key
        except Exception as exc:  # fail-open
            logger.debug("cairn mint failed: %s", exc)
            return None

    async def submit(self, event: ScoreEvent) -> None:
        if self.config.offline:
            return
        key = await self._ensure_key()
        if key is None:
            return
        try:
            resp = await self._http.post(
                "/v1/scores", json=event.to_payload(), headers={"X-Api-Key": key},
            )
            resp.raise_for_status()
        except Exception as exc:  # fail-open
            logger.debug("cairn submit failed: %s", exc)

    async def submit_batch(self, events: list[ScoreEvent]) -> None:
        if self.config.offline or not events:
            return
        key = await self._ensure_key()
        if key is None:
            return
        for start in range(0, len(events), 100):
            chunk = events[start : start + 100]
            try:
                resp = await self._http.post(
                    "/v1/scores/batch",
                    json={"events": [e.to_payload() for e in chunk]},
                    headers={"X-Api-Key": key},
                )
                resp.raise_for_status()
            except Exception as exc:  # fail-open
                logger.debug("cairn submit_batch chunk failed: %s", exc)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_client_writes.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/academy_cairn/client.py tests/unit/test_client_writes.py
git commit -m "feat: CairnClient writes + lazy mint with collision retry (M1)"
```

---

### Task 7: Offline queue + flusher + CLI (M3, built before the guard)

**Files:**
- Modify: `src/academy_cairn/queue.py`, `src/academy_cairn/client.py`
- Test: `tests/unit/test_queue.py`

**Interfaces:**
- Consumes: `ScoreEvent` (Task 3), `CairnClient.submit_batch` (Task 6).
- Produces:
  - `ScoreQueue(path: Path)` with:
    - `enqueue(event: ScoreEvent) -> None` — sync, O(1), appends one JSON line.
    - `read_all() -> list[ScoreEvent]` — parses lines, skips+warns on corrupt lines.
    - `async flush(submit_batch) -> int` — drains in ≤100 batches via the passed `async submit_batch(list[ScoreEvent])`; rewrites the file to drop only acknowledged lines after each successful batch; returns count flushed. Kill-before-rewrite ⇒ at-least-once (documented).
  - On `CairnClient`: `enqueue(event)` (delegates to its `ScoreQueue`), `async flush()` (calls `self._queue.flush(self.submit_batch)`), constructor gains `queue_path: Path | None`.
  - CLI `python -m academy_cairn.flush` in `queue.py` `main()` that builds a client from `CairnConfig` + identity and flushes the on-disk queue once.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_queue.py
import pytest
from academy_cairn.queue import ScoreQueue
from academy_cairn.entity import EntityRef, ScoreEvent


def _event(i):
    return ScoreEvent(reviewee=EntityRef(type="data_source", external_id=f"https://a/{i}"), score=0.5)


def test_enqueue_appends_lines(tmp_path):
    q = ScoreQueue(tmp_path / "q.jsonl")
    q.enqueue(_event(0))
    q.enqueue(_event(1))
    assert len(q.read_all()) == 2


def test_read_all_skips_corrupt_lines(tmp_path):
    path = tmp_path / "q.jsonl"
    q = ScoreQueue(path)
    q.enqueue(_event(0))
    with path.open("a") as fh:
        fh.write("{ this is not json\n")
    q.enqueue(_event(1))
    assert len(q.read_all()) == 2  # corrupt line skipped, valid ones kept


@pytest.mark.asyncio
async def test_flush_drains_in_batches_and_empties(tmp_path):
    q = ScoreQueue(tmp_path / "q.jsonl")
    for i in range(150):
        q.enqueue(_event(i))
    sizes = []
    async def fake_submit(events):
        sizes.append(len(events))
    n = await q.flush(fake_submit)
    assert n == 150
    assert sizes == [100, 50]
    assert q.read_all() == []  # fully drained


@pytest.mark.asyncio
async def test_flush_keeps_events_when_submit_fails(tmp_path):
    q = ScoreQueue(tmp_path / "q.jsonl")
    q.enqueue(_event(0))
    async def failing_submit(events):
        raise RuntimeError("network down")
    n = await q.flush(failing_submit)
    assert n == 0
    assert len(q.read_all()) == 1  # nothing lost on failure
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_queue.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `queue.py`**

```python
# src/academy_cairn/queue.py
"""Append-only JSONL write queue with a batch flusher."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Awaitable, Callable

from .config import CairnConfig
from .entity import ScoreEvent
from .identity import (
    KeyStore, agent_name_from, identity_slug, reviewer_external_id,
)

logger = logging.getLogger("academy_cairn")

SubmitBatch = Callable[[list[ScoreEvent]], Awaitable[None]]


class ScoreQueue:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def enqueue(self, event: ScoreEvent) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as fh:
            fh.write(event.model_dump_json(exclude_none=True) + "\n")

    def read_all(self) -> list[ScoreEvent]:
        if not self._path.exists():
            return []
        events: list[ScoreEvent] = []
        for line in self._path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(ScoreEvent.model_validate_json(line))
            except Exception as exc:
                logger.warning("skipping corrupt queue line: %s", exc)
        return events

    def _rewrite(self, remaining: list[ScoreEvent]) -> None:
        if not remaining:
            self._path.write_text("")
            return
        self._path.write_text(
            "\n".join(e.model_dump_json(exclude_none=True) for e in remaining) + "\n"
        )

    async def flush(self, submit_batch: SubmitBatch) -> int:
        pending = self.read_all()
        flushed = 0
        while pending:
            chunk, pending = pending[:100], pending[100:]
            try:
                await submit_batch(chunk)
            except Exception as exc:
                logger.debug("flush chunk failed, keeping events: %s", exc)
                self._rewrite(chunk + pending)
                return flushed
            flushed += len(chunk)
            self._rewrite(pending)  # drop only acknowledged lines
        return flushed
```

- [ ] **Step 4: Wire the queue into `CairnClient`**

In `client.py`, add `from pathlib import Path` and `from .queue import ScoreQueue`. Extend `__init__` signature with `queue_path: Path | None = None` and set:

```python
        self._queue = ScoreQueue(queue_path) if queue_path is not None else None

    def enqueue(self, event: ScoreEvent) -> None:
        if self._queue is not None:
            self._queue.enqueue(event)

    async def flush(self) -> int:
        if self._queue is None or self.config.offline:
            return 0
        return await self._queue.flush(self.submit_batch)
```

- [ ] **Step 5: Add the CLI `main()` to `queue.py`**

```python
def _default_queue_path(config: CairnConfig, slug: str) -> Path:
    return config.key_dir.parent / "queue" / f"{slug}.jsonl"


def main() -> None:
    import asyncio
    import socket
    from .client import CairnClient

    config = CairnConfig()
    reviewer = reviewer_external_id(config.namespace, agent_name_from(None, "cli00000"))
    slug = identity_slug(reviewer)
    host = socket.gethostname()
    client = CairnClient(
        config, reviewer_id=reviewer, uid="cli00000",
        key_store=KeyStore(config.key_dir, host),
        queue_path=_default_queue_path(config, slug),
    )

    async def _run() -> None:
        n = await client.flush()
        logger.info("flushed %d events", n)
        await client.aclose()

    asyncio.run(_run())


if __name__ == "__main__":  # python -m academy_cairn.flush maps here via flush.py
    main()
```

Also create `src/academy_cairn/flush.py` with `from .queue import main; main()` so `python -m academy_cairn.flush` works.

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/unit/test_queue.py -q`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add src/academy_cairn/queue.py src/academy_cairn/flush.py src/academy_cairn/client.py tests/unit/test_queue.py
git commit -m "feat: JSONL write queue + flusher + flush CLI (M3)"
```

---

### Task 8: Heuristic rater (M2)

**Files:**
- Modify: `src/academy_cairn/rater.py`
- Test: `tests/unit/test_rater.py`

**Interfaces:**
- Consumes: `EntityRef`, `ScoreEvent`, `snake_case` (Task 3).
- Produces:
  - `latency_score(elapsed_s: float) -> float` → `<1 ⇒ 1.0`, `<5 ⇒ 0.7`, else `0.4`.
  - `rate_outcome(ref, *, success, elapsed_s, exc=None, weight, context="general") -> ScoreEvent`:
    - success ⇒ `score=0.75`, `dimensions={"reliability":1.0, "latency":latency_score(...)}`, `metrics={"latency_ms":...}`, rationale mentions only `ref.external_id`.
    - failure ⇒ `score=0.2`, `dimensions={"reliability":0.0}`, `failure_modes=[snake_case(type(exc).__name__)]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_rater.py
from academy_cairn.rater import latency_score, rate_outcome
from academy_cairn.entity import EntityRef

REF = EntityRef(type="data_source", external_id="https://a/v1")


def test_latency_score_bands():
    assert latency_score(0.5) == 1.0
    assert latency_score(3.0) == 0.7
    assert latency_score(9.0) == 0.4


def test_success_event():
    ev = rate_outcome(REF, success=True, elapsed_s=0.5, weight=0.3)
    assert ev.score == 0.75
    assert ev.dimensions == {"reliability": 1.0, "latency": 1.0}
    assert ev.metrics["latency_ms"] == 500.0
    assert ev.weight == 0.3
    assert "https://a/v1" in ev.rationale


def test_failure_event_uses_exception_class():
    ev = rate_outcome(REF, success=False, elapsed_s=2.0, exc=TimeoutError(), weight=0.3)
    assert ev.score == 0.2
    assert ev.dimensions == {"reliability": 0.0}
    assert ev.failure_modes == ["timeout_error"]


def test_rationale_never_leaks_args():
    # rationale must only ever contain the entity id, never other values
    ev = rate_outcome(REF, success=True, elapsed_s=0.1, weight=0.3)
    assert ev.rationale.count("https://a/v1") == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_rater.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
# src/academy_cairn/rater.py
"""Map an observed action/handle outcome to a Cairn ScoreEvent (no LLM)."""
from __future__ import annotations

from .entity import EntityRef, ScoreEvent, snake_case


def latency_score(elapsed_s: float) -> float:
    if elapsed_s < 1.0:
        return 1.0
    if elapsed_s < 5.0:
        return 0.7
    return 0.4


def rate_outcome(
    ref: EntityRef,
    *,
    success: bool,
    elapsed_s: float,
    exc: BaseException | None = None,
    weight: float,
    context: str = "general",
) -> ScoreEvent:
    if success:
        return ScoreEvent(
            reviewee=ref,
            score=0.75,
            weight=weight,
            context=context,
            dimensions={"reliability": 1.0, "latency": latency_score(elapsed_s)},
            metrics={"latency_ms": round(elapsed_s * 1000, 1)},
            rationale=f"Automated outcome rating for {ref.external_id}: success.",
        )
    return ScoreEvent(
        reviewee=ref,
        score=0.2,
        weight=weight,
        context=context,
        dimensions={"reliability": 0.0},
        failure_modes=[snake_case(type(exc).__name__)] if exc else ["unknown"],
        rationale=f"Automated outcome rating for {ref.external_id}: failure.",
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_rater.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/academy_cairn/rater.py tests/unit/test_rater.py
git commit -m "feat: heuristic outcome->rating mapper (M2)"
```

---

### Task 9: `@cairn_guarded` + `TrustPolicy` (M2)

**Files:**
- Modify: `src/academy_cairn/guard.py`
- Test: `tests/unit/test_guard.py`

**Interfaces:**
- Consumes: `CairnClient` (via duck-typed `self.cairn` exposing `get_score`, `enqueue`, `config.default_weight`), `EntityRef`, `Reading`, `rate_outcome` (Tasks 5–8).
- Produces:
  - `TrustPolicy(BaseModel)`: `min_score=0.4`, `min_confidence=0.3`, `on_low: Literal["log","warn","block"]="log"`.
  - `CairnTrustError(RuntimeError)`.
  - `cairn_guarded(*, type: EntityType, id_from: str | Callable, policy=None, rate=True, context="general", weight=None)` → decorator returning an `async` wrapper (uses `functools.wraps`, so `@action` above it still marks it as an action). If `self.cairn` is absent/`None`, wrapper is a pass-through (no-op). Pre: `get_score` → policy (`block` raises `CairnTrustError` only when `confidence >= min_confidence` and `score < min_score`). Post: enqueue `rate_outcome(...)` on success and (before re-raising) on exception.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_guard.py
import pytest
from academy_cairn.guard import cairn_guarded, TrustPolicy, CairnTrustError
from academy_cairn.entity import EntityRef, Reading


class FakeCairn:
    def __init__(self, reading):
        self._reading = reading
        self.enqueued = []
        class C: default_weight = 0.3
        self.config = C()
    async def get_score(self, ref): return self._reading
    def enqueue(self, event): self.enqueued.append(event)


class Agent:
    def __init__(self, cairn): self.cairn = cairn

    @cairn_guarded(type="data_source", id_from="url", policy=TrustPolicy(on_low="block"))
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_guard.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
# src/academy_cairn/guard.py
"""@cairn_guarded: pre-check trust, run the action, post-rate the outcome."""
from __future__ import annotations

import functools
import inspect
import logging
import time
from typing import Callable, Literal

from pydantic import BaseModel

from .entity import EntityRef, EntityType
from .rater import rate_outcome

logger = logging.getLogger("academy_cairn")


class TrustPolicy(BaseModel):
    min_score: float = 0.4
    min_confidence: float = 0.3
    on_low: Literal["log", "warn", "block"] = "log"


class CairnTrustError(RuntimeError):
    def __init__(self, ref: EntityRef, reading) -> None:
        super().__init__(f"Cairn policy blocked {ref.external_id} (score={reading.composite_score})")
        self.ref = ref
        self.reading = reading


def _resolve_ref(entity_type, id_from, sig, self_obj, args, kwargs) -> EntityRef | None:
    try:
        if callable(id_from):
            result = id_from(self_obj, *args, **kwargs)
            return result if isinstance(result, EntityRef) else EntityRef(type=entity_type, external_id=str(result))
        bound = sig.bind(self_obj, *args, **kwargs)
        bound.apply_defaults()
        value = bound.arguments[id_from]
        return EntityRef(type=entity_type, external_id=str(value))
    except Exception as exc:  # fail-open: can't resolve ⇒ skip guarding
        logger.debug("cairn could not resolve entity ref: %s", exc)
        return None


async def _pre_check(cairn, ref, policy: TrustPolicy) -> None:
    reading = await cairn.get_score(ref)
    if reading.confidence < policy.min_confidence:
        return  # no data ⇒ always proceed
    if reading.composite_score >= policy.min_score:
        return
    if policy.on_low == "block":
        raise CairnTrustError(ref, reading)
    log = logger.warning if policy.on_low == "warn" else logger.info
    log("cairn low-trust %s score=%.2f conf=%.2f", ref.external_id, reading.composite_score, reading.confidence)


def cairn_guarded(
    *,
    type: EntityType,
    id_from: str | Callable,
    policy: TrustPolicy | None = None,
    rate: bool = True,
    context: str = "general",
    weight: float | None = None,
):
    the_policy = policy or TrustPolicy()

    def decorator(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(self, *args, **kwargs):
            cairn = getattr(self, "cairn", None)
            ref = _resolve_ref(type, id_from, sig, self, args, kwargs) if cairn is not None else None
            if cairn is not None and ref is not None:
                try:
                    await _pre_check(cairn, ref, the_policy)
                except CairnTrustError:
                    raise
                except Exception as exc:  # fail-open on Cairn errors
                    logger.debug("cairn pre-check failed open: %s", exc)
            start = time.monotonic()
            try:
                result = await fn(self, *args, **kwargs)
            except Exception as exc:
                if cairn is not None and ref is not None and rate:
                    w = weight if weight is not None else cairn.config.default_weight
                    cairn.enqueue(rate_outcome(ref, success=False, elapsed_s=time.monotonic() - start, exc=exc, weight=w, context=context))
                raise
            if cairn is not None and ref is not None and rate:
                w = weight if weight is not None else cairn.config.default_weight
                cairn.enqueue(rate_outcome(ref, success=True, elapsed_s=time.monotonic() - start, weight=w, context=context))
            return result

        return wrapper

    return decorator
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_guard.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/academy_cairn/guard.py tests/unit/test_guard.py
git commit -m "feat: @cairn_guarded decorator + TrustPolicy (M2)"
```

---

### Task 10: `CairnAgentMixin` (M2/M3 lifecycle wiring)

**Files:**
- Modify: `src/academy_cairn/mixin.py`
- Test: `tests/unit/test_mixin.py`

**Interfaces:**
- Consumes: `CairnConfig`, `CairnClient`, identity helpers, `KeyStore` (Tasks 2–7).
- Produces:
  - `CairnAgentMixin`: intended to be mixed into an Academy `Agent`. Provides `self.cairn: CairnClient | None`.
  - `async agent_on_startup()`: if `config.enabled`, build a `CairnClient` (reviewer id from `AgentId` via identity helpers; `queue_path` under `key_dir.parent/"queue"`), and start a background flush loop every `flush_interval_s` (skipped when `offline`). Calls `super().agent_on_startup()`.
  - `async agent_on_shutdown()`: cancel the loop, `await self.cairn.flush()`, `await self.cairn.aclose()`. Calls `super().agent_on_shutdown()`.
  - `async discover(query, k=5)`: convenience delegating to `self.cairn.discover` (returns `[]` if disabled).
- The mixin reads `self.agent_id` (Academy sets `AgentId(uid, name)` on the running agent). For test isolation, `_build_client()` is a separate method taking `namespace`, `name`, `uid` so it can be exercised without a full Academy runtime.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mixin.py
import httpx
import pytest
from academy_cairn.mixin import CairnAgentMixin
from academy_cairn.config import CairnConfig


def _handler(req):
    if req.url.path == "/v1/discover":
        return httpx.Response(200, json={"results": [{"entity": {"external_id": "mcp://x"}}]})
    return httpx.Response(200, json={})


@pytest.mark.asyncio
async def test_build_client_uses_identity(tmp_path):
    m = CairnAgentMixin()
    client = m._build_client(
        CairnConfig(namespace="argus", key_dir=tmp_path),
        name="triage", uid="uid00000000",
        transport=httpx.MockTransport(_handler),
    )
    assert client._reviewer_id == "agent://academy/argus/triage"
    await client.aclose()


@pytest.mark.asyncio
async def test_disabled_config_yields_no_client():
    m = CairnAgentMixin()
    m._cairn_config = CairnConfig(enabled=False)
    m.agent_id = type("A", (), {"uid": "u", "name": "n"})()
    # startup with disabled config leaves self.cairn None and does not raise
    await CairnAgentMixin.agent_on_startup(m)
    assert m.cairn is None
```

Note: `test_disabled_config_yields_no_client` calls the mixin method directly; the mixin must tolerate not being inside a real `Agent` (guard the `super()` call — see implementation).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_mixin.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
# src/academy_cairn/mixin.py
"""Mixin that wires a CairnClient into the Academy agent lifecycle."""
from __future__ import annotations

import asyncio
import logging
import socket
from pathlib import Path

import httpx

from .client import CairnClient
from .config import CairnConfig
from .identity import (
    KeyStore, agent_name_from, identity_slug, reviewer_external_id,
)

logger = logging.getLogger("academy_cairn")


class CairnAgentMixin:
    cairn: CairnClient | None = None
    _cairn_config: CairnConfig | None = None
    _cairn_flush_task: asyncio.Task | None = None

    def _config(self) -> CairnConfig:
        if self._cairn_config is None:
            self._cairn_config = CairnConfig()
        return self._cairn_config

    def _build_client(
        self,
        config: CairnConfig,
        *,
        name: str | None,
        uid: str,
        transport: httpx.BaseTransport | None = None,
    ) -> CairnClient:
        reviewer = reviewer_external_id(config.namespace, agent_name_from(name, uid))
        slug = identity_slug(reviewer)
        host = socket.gethostname()
        queue_path = config.key_dir.parent / "queue" / f"{slug}.jsonl"
        return CairnClient(
            config,
            reviewer_id=reviewer,
            uid=uid,
            key_store=KeyStore(config.key_dir, host),
            queue_path=queue_path,
            transport=transport,
        )

    async def agent_on_startup(self) -> None:
        config = self._config()
        if config.enabled:
            agent_id = getattr(self, "agent_id", None)
            name = getattr(agent_id, "name", None)
            uid = str(getattr(agent_id, "uid", "00000000"))
            self.cairn = self._build_client(config, name=name, uid=uid)
            if not config.offline:
                self._cairn_flush_task = asyncio.create_task(self._flush_loop())
        parent_startup = getattr(super(), "agent_on_startup", None)
        if parent_startup is not None:
            await parent_startup()

    async def _flush_loop(self) -> None:
        assert self.cairn is not None
        interval = self._config().flush_interval_s
        try:
            while True:
                await asyncio.sleep(interval)
                await self.cairn.flush()
        except asyncio.CancelledError:
            pass

    async def agent_on_shutdown(self) -> None:
        if self._cairn_flush_task is not None:
            self._cairn_flush_task.cancel()
        if self.cairn is not None:
            await self.cairn.flush()
            await self.cairn.aclose()
        parent_shutdown = getattr(super(), "agent_on_shutdown", None)
        if parent_shutdown is not None:
            await parent_shutdown()

    async def discover(self, query: str, k: int = 5) -> list[dict]:
        if self.cairn is None:
            return []
        return await self.cairn.discover(query, k)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_mixin.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/academy_cairn/mixin.py tests/unit/test_mixin.py
git commit -m "feat: CairnAgentMixin lifecycle + flusher + discover (M2/M3)"
```

---

### Task 11: `rated(handle)` peer rating proxy (M4)

**Files:**
- Modify: `src/academy_cairn/peers.py`, `src/academy_cairn/__init__.py`
- Test: `tests/unit/test_peers.py`

**Interfaces:**
- Consumes: `CairnClient` (via `enqueue`, `config`), `agent_entity`, `rate_outcome` (Tasks 3, 5–8).
- Produces:
  - `rated(handle, *, cairn) -> RatedHandle` — wraps an Academy `Handle`.
  - `RatedHandle`: `__getattr__` delegates to the wrapped handle; but calling `.action(name, *a, **k)` (and attribute-style action calls, which Academy routes through `action()`) times the call and enqueues a peer rating on entity `agent://academy/{ns}/{peer_name}`. Success ⇒ `rate_outcome(success=True,...)`; exception (incl. `AgentTerminatedError`) ⇒ low rating, then re-raise. Non-invocation attributes (`agent_id`, `shutdown`, `ping`, …) pass through unwrapped.
  - `RatedHandle.__reduce__` returns the **inner** handle, so accidental serialization degrades to a plain working handle.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_peers.py
import pickle
import pytest
from academy_cairn.peers import rated
from academy_cairn.entity import Reading


class FakeCairn:
    def __init__(self):
        self.enqueued = []
        class C: default_weight = 0.3
        self.config = C()
    def enqueue(self, e): self.enqueued.append(e)


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_peers.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
# src/academy_cairn/peers.py
"""rated(handle): score peer agents from Handle invocation outcomes."""
from __future__ import annotations

import time
from typing import Any

from .entity import agent_entity
from .rater import rate_outcome


class RatedHandle:
    def __init__(self, handle: Any, *, cairn: Any) -> None:
        object.__setattr__(self, "_handle", handle)
        object.__setattr__(self, "_cairn", cairn)

    def _peer_ref(self):
        agent_id = getattr(self._handle, "agent_id", None)
        name = getattr(agent_id, "name", None) or f"anon-{str(getattr(agent_id, 'uid', ''))[:8]}"
        namespace = self._cairn.config.namespace if hasattr(self._cairn, "config") else "unknown"
        return agent_entity(namespace, name)

    async def action(self, name, /, *args, **kwargs):
        ref = self._peer_ref()
        weight = self._cairn.config.default_weight
        start = time.monotonic()
        try:
            result = await self._handle.action(name, *args, **kwargs)
        except Exception as exc:
            self._cairn.enqueue(rate_outcome(ref, success=False, elapsed_s=time.monotonic() - start, exc=exc, weight=weight))
            raise
        self._cairn.enqueue(rate_outcome(ref, success=True, elapsed_s=time.monotonic() - start, weight=weight))
        return result

    def __getattr__(self, item):
        # non-invocation attributes pass through unwrapped
        return getattr(object.__getattribute__(self, "_handle"), item)

    def __reduce__(self):
        # accidental serialization degrades to the plain inner handle
        return (_identity, (object.__getattribute__(self, "_handle"),))


def _identity(handle):
    return handle


def rated(handle: Any, *, cairn: Any) -> RatedHandle:
    return RatedHandle(handle, cairn=cairn)
```

Note: `_identity` must be module-level so pickle can import it; `__reduce__` returns the inner handle instance directly via the identity callable.

- [ ] **Step 4: Export the public API in `__init__.py`**

```python
# src/academy_cairn/__init__.py
"""academy-cairn public API."""
from .client import CairnClient
from .config import CairnConfig
from .entity import EntityRef, Reading, ScoreEvent
from .guard import cairn_guarded, CairnTrustError, TrustPolicy
from .mixin import CairnAgentMixin
from .peers import rated

__all__ = [
    "CairnClient", "CairnConfig", "EntityRef", "Reading", "ScoreEvent",
    "cairn_guarded", "CairnTrustError", "TrustPolicy", "CairnAgentMixin", "rated",
]
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/unit/test_peers.py -q && uv run pytest -q`
Expected: PASS (all tests green).

- [ ] **Step 6: Commit**

```bash
git add src/academy_cairn/peers.py src/academy_cairn/__init__.py tests/unit/test_peers.py
git commit -m "feat: rated(handle) peer-rating proxy + public API (M4)"
```

---

### Task 12: Integration tests (skip-guarded on `CAIRN_TEST_URL`)

**Files:**
- Create: `tests/integration/__init__.py`, `tests/integration/conftest.py`, `tests/integration/test_roundtrip.py`

**Interfaces:**
- Consumes: full public API. Runs only when `CAIRN_TEST_URL` is set (local cairn-service via its `make up`).

- [ ] **Step 1: Write the integration test**

```python
# tests/integration/conftest.py
import os
import pytest

CAIRN_TEST_URL = os.environ.get("CAIRN_TEST_URL")
pytestmark = pytest.mark.skipif(not CAIRN_TEST_URL, reason="set CAIRN_TEST_URL to run")
```

```python
# tests/integration/test_roundtrip.py
import os
import uuid
import pytest
from academy_cairn.config import CairnConfig
from academy_cairn.client import CairnClient
from academy_cairn.identity import KeyStore
from academy_cairn.entity import EntityRef, ScoreEvent

pytestmark = pytest.mark.skipif(
    not os.environ.get("CAIRN_TEST_URL"), reason="set CAIRN_TEST_URL to run",
)


@pytest.mark.asyncio
async def test_mint_write_read(tmp_path):
    base = os.environ["CAIRN_TEST_URL"]
    reviewer = f"agent://academy/itest/{uuid.uuid4().hex[:8]}"
    ext = f"https://itest.example/{uuid.uuid4().hex[:8]}"
    client = CairnClient(
        CairnConfig(base_url=base),
        reviewer_id=reviewer, uid=uuid.uuid4().hex,
        key_store=KeyStore(tmp_path, host="itest"),
        queue_path=tmp_path / "q.jsonl",
    )
    ref = EntityRef(type="data_source", external_id=ext)
    before = await client.get_score(ref)
    assert before.confidence == 0.0  # unknown entity
    await client.submit(ScoreEvent(reviewee=ref, score=0.9))
    after = await client.get_score(ref)
    assert after.confidence > 0.0  # evidence now recorded
    await client.aclose()
```

- [ ] **Step 2: Run (skipped without the env var)**

Run: `uv run pytest tests/integration -q`
Expected: `2 skipped` (no `CAIRN_TEST_URL`). With cairn-service up and `CAIRN_TEST_URL` set: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration
git commit -m "test: integration roundtrip against local cairn-service (M1)"
```

---

## Self-Review

**Spec coverage:**
- Goals 1–4 → Tasks 5/6 (reads zero-setup, lazy mint), 9 (guard), 11 (peer rating), 7+10 (async/offline queue/flush). ✓
- Locked decisions 1 (identity/collision) → Tasks 4, 6; 2 (peer entity formula) → Task 11; 3 (fail-open) → Tasks 5, 6, 9 tests; 4 (default log, block needs confidence) → Task 9; 5 (writes via queue) → Tasks 7, 9, 11; 6 (weight 0.3) → Tasks 2, 8. ✓
- Brainstorm decisions 7 (per-agent transport) → Task 5; 8 (context general) → default in `ScoreEvent`/rater; 9 (latency bands) → Task 8; 10 (discover on mixin) → Task 10. ✓
- Cairn contract (endpoints, mint 409/422, unknown ⇒ 0.5/0.0, batch ≤100) → Tasks 5, 6, 12. ✓
- Testing strategy (MockTransport unit, skip-guarded integration, ProxyHandle-style M4) → all unit tasks + Task 12; Task 11 uses a `FakeHandle` standing in for `ProxyHandle`. ✓

**Placeholder scan:** none — every code and test step is concrete.

**Type consistency:** `rate_outcome` signature identical in Tasks 8/9/11; `CairnClient.enqueue`/`flush`/`submit_batch` names consistent across Tasks 6/7/10; `Reading.no_data()` used identically in Tasks 5/9/12; `self.cairn.config.default_weight` accessed the same way in guard and peers.

**Deviation notes (intentional, from the spec):**
1. Queue (spec M3) is built before the guard (spec M2) so the guard's post-rate enqueues into a real queue — avoids a throwaway direct-write path (honors locked decision 5).
2. The per-agent `ScoreQueue` is owned by `CairnClient` rather than a standalone module wired separately, so `self.cairn` exposes both `get_score()` and `enqueue()` exactly as the spec's guard section assumes.
3. A `flush.py` shim is added so `python -m academy_cairn.flush` resolves (the spec named that CLI entry point but not the module file).
