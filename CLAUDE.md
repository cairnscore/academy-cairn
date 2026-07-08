# academy-cairn — Claude Code instructions

Trust-aware Academy agents backed by Cairn. Pure client library: it talks to the
Cairn `/v1` HTTP API and composes with Academy's public seams (`@action`,
`agent_on_startup`/`agent_on_shutdown`, `Handle.action`). It does **not** modify
Academy and it does **not** run a server or a database.

See `docs/superpowers/specs/` for the design spec and `docs/superpowers/plans/`
for the implementation plan.

## Package management: always use uv

This project uses [uv](https://github.com/astral-sh/uv). Never use `pip`,
`python -m pip`, or bare `python` to install packages or run tools.

```bash
uv sync --extra dev                    # install / sync deps
uv run pytest                          # run tests
uv run ruff check src/ tests/
uv run mypy src/
uv run python -m academy_cairn.flush   # drain the offline queue
```

The venv lives at `.venv/`. Never activate it manually; `uv run` handles it.

## Code conventions

- **Python 3.10+** — match Academy's floor. Use `X | Y` union syntax (with
  `from __future__ import annotations` at the top of every module), never
  `Optional[X]` or `Union[X, Y]`.
- **Types:** all functions must have type annotations (mypy `strict = true`).
- **No comments explaining what code does.** Only add a comment when the *why*
  is non-obvious (e.g. the `# fail-open` markers on the client's `except`
  blocks).
- **Line length:** 88 (ruff enforced).
- **pydantic v2** for all data models. Prefer small, single-responsibility
  modules — one clear purpose per file (see the package layout in the spec).

## Fail-open is a hard rule

Every path that touches Cairn must degrade gracefully. Any Cairn error —
transport failure, timeout, 4xx/5xx, rate limit — is caught, logged at
`debug` (or `warning` for identity collisions), and the guarded action / Handle
call proceeds anyway. A Cairn outage must never break an agent. This is enforced
by tests; keep it that way when adding methods.

## Cairn API notes

- **Reads are unauthenticated** (`GET /v1/score`, `POST /v1/score/batch`,
  `GET /v1/profile`, `POST /v1/discover`, `POST /v1/rank`). **Writes require**
  the `X-Api-Key` header (`POST /v1/scores`, `POST /v1/scores/batch`).
- **Never re-implement external_id normalization client-side.** The server
  normalizes on every read and write. Send the raw id you have; responses echo
  the canonical form.
- **Unknown entities** come back as `composite_score: 0.5, confidence: 0.0`.
  Treat that as "no data", never as "bad" — never block on it.
- **Lazy key minting** via `POST /v1/keys` is claim-once: `409` on a claimed
  identity, `422` on a reserved prefix. On a `409` with no local key, retry once
  with a `-{uid[:8]}` suffix and log a warning.
- **Batch cap is 100 events**; the queue flusher chunks accordingly.
- No server-side idempotency: on a write timeout, treat the rating as submitted
  and move on. At-least-once delivery from the offline queue is accepted and
  documented — don't add blind retries that double-count.

## Testing

```bash
uv run pytest                     # full suite
uv run pytest tests/unit/         # no network — httpx.MockTransport only
uv run pytest tests/integration/  # skipped unless CAIRN_TEST_URL is set
```

- **Unit tests use `httpx.MockTransport`** — no network, no Academy runtime.
  Inject the transport via `CairnClient(..., transport=...)`.
- **Integration tests skip-guard on `CAIRN_TEST_URL`**, pointed at a local
  cairn-service (`make up` in that repo). They mint → write → read against a
  real backend.
- `pytest-asyncio` is configured with `asyncio_mode = "auto"` — no
  `@pytest.mark.asyncio` needed (it's fine to keep them for clarity).

## Git commits

Commit proactively after substantial coherent work — a completed milestone/task,
a finished feature, a bug fix with its test, a meaningful refactor. Don't wait to
be asked. Tiny in-progress edits don't need their own commit.

- One commit per logical unit. A plan task is one commit.
- Message style: `<short subject>`, blank line, prose body explaining the *why*
  and any non-obvious decisions. Feature work uses a `feat:`/`chore:`/`test:`
  prefix; milestone context goes in the body (e.g. "(M1)").
- Include the trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Tests, ruff, and mypy must be clean before committing.

## Linting and type checking

Run both before committing:

```bash
uv run ruff check src/ tests/
uv run mypy src/
```

Fix import-order issues with `uv run ruff check --fix`.

## Working principles

### Think before coding

- If multiple interpretations of the request exist, present them — don't pick
  silently.
- If a simpler approach exists, say so. Push back when warranted.
- If you'd have to guess on something a senior engineer would pull you aside to
  clarify, ask.

### Simplicity first

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes,
simplify.

### Surgical changes

Touch only what you must. Clean up only your own mess.

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.
- Remove imports/variables/functions that YOUR changes made unused; leave
  pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

### Goal-driven execution

Before non-trivial work, name what "done" looks like — the check, test, or
observable behavior that tells you you're finished. This package is TDD: for each
plan task, the failing test is the goal, and green + clean lint/types is done.
