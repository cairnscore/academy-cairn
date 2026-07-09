"""Build a CairnClient for an agent and, when needed, self-install its flush
lifecycle.

`CairnAgentMixin` wires the client explicitly via the agent lifecycle. But
`@cairn_guarded` and `rated(...)` also work on a plain Academy `Agent` with no
mixin: the first time they run, they lazily provision a client from the agent's
identity and attach a background flusher plus a shutdown flush to the agent
instance. Academy invokes `agent_on_shutdown` on the instance, so an
instance-level hook is honored.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from typing import Any

import httpx

from .client import CairnClient
from .config import CairnConfig
from .identity import (
    KeyStore,
    agent_name_from,
    identity_slug,
    reviewer_external_id,
)

logger = logging.getLogger("academy_cairn")


def build_client(
    config: CairnConfig,
    *,
    name: str | None,
    uid: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CairnClient:
    """Build a CairnClient for one agent identity (reviewer, key store, queue)."""
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


def ensure_client(agent: Any) -> CairnClient | None:
    """Return ``agent.cairn``, lazily provisioning it (with flush lifecycle) if
    absent. Returns None when trust is disabled or the object has no agent
    identity, in which case the caller should no-op (fail-open)."""
    existing: CairnClient | None = getattr(agent, "cairn", None)
    if existing is not None:
        return existing  # mixin, or a prior lazy provision

    config = CairnConfig()
    if not config.enabled:
        return None
    agent_id = getattr(agent, "agent_id", None)
    if agent_id is None:
        return None  # not a running Academy agent; nothing to key against

    name = getattr(agent_id, "name", None)
    uid = str(getattr(agent_id, "uid", "") or "0")
    client = build_client(config, name=name, uid=uid)
    try:
        agent.cairn = client  # cache so later calls + getattr find it
    except Exception:  # object doesn't accept attributes; use it just this call
        return client
    _install_lifecycle(agent, client, config)
    return client


def _install_lifecycle(agent: Any, client: CairnClient, config: CairnConfig) -> None:
    if getattr(agent, "_cairn_lifecycle_installed", False):
        return
    agent._cairn_lifecycle_installed = True

    if not config.offline:
        with contextlib.suppress(RuntimeError):  # no running loop ⇒ no flusher
            agent._cairn_flush_task = asyncio.create_task(
                _flush_loop(client, config.flush_interval_s),
            )

    original_shutdown = getattr(agent, "agent_on_shutdown", None)

    async def _shutdown() -> None:
        task = getattr(agent, "_cairn_flush_task", None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        with contextlib.suppress(Exception):  # fail-open: never break shutdown
            await client.flush()
            await client.aclose()
        if original_shutdown is not None:
            await original_shutdown()

    agent.agent_on_shutdown = _shutdown


async def _flush_loop(client: CairnClient, interval: float) -> None:
    try:
        while True:
            await asyncio.sleep(interval)
            await client.flush()
    except asyncio.CancelledError:
        pass
