"""Shared setup for the academy-cairn demos.

These demos run *real* Academy agents on Academy's in-process ``LocalExchange``
(no external services beyond Cairn itself). Each agent mixes in
``CairnAgentMixin``, so ``self.cairn`` is created, keyed, and flushed for you
across the agent lifecycle — you only add the mixin and a ``@cairn_guarded``
line, exactly as you would in production.

Point the demos at any Cairn deployment by setting ``CAIRN_BASE_URL`` (defaults
to the hosted service at https://api.cairnscore.ai). Set ``CAIRN_NAMESPACE`` to
group your agents' identities (the demos suggest ``CAIRN_NAMESPACE=demo``).
Reads are unauthenticated; the first rating an agent submits lazily mints an API
key for its identity and caches it under ``~/.cairn/academy/keys``.
"""

from __future__ import annotations

import contextlib
import socket
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from academy.exchange import LocalExchangeFactory
from academy.manager import Manager

from academy_cairn import CairnClient, CairnConfig
from academy_cairn.identity import KeyStore, reviewer_external_id


@contextlib.asynccontextmanager
async def academy() -> AsyncIterator[Manager]:
    """An in-process Academy runtime: launch agents, get handles, call actions."""
    from concurrent.futures import ThreadPoolExecutor

    async with await Manager.from_exchange_factory(
        factory=LocalExchangeFactory(),
        executors=ThreadPoolExecutor(),
    ) as manager:
        yield manager


def reader() -> CairnClient:
    """A read-only Cairn client for looking up scores (reads need no key)."""
    config = CairnConfig()
    return CairnClient(
        config,
        reviewer_id=reviewer_external_id(config.namespace, "reader"),
        uid=uuid.uuid4().hex,
        key_store=KeyStore(config.key_dir, socket.gethostname()),
        queue_path=Path(tempfile.gettempdir()) / "cairn-demo-reader.jsonl",
    )


def demo_entity(label: str) -> str:
    """A fresh external_id per run, so every demo starts from a clean slate."""
    return f"https://{label}.demo.example/{uuid.uuid4().hex[:8]}"


def bar(value: float, width: int = 20) -> str:
    """A tiny text meter for a value in [0, 1] — nice on a terminal/slide."""
    filled = round(value * width)
    return "█" * filled + "░" * (width - filled)
