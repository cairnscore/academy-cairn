"""Mixin that wires a CairnClient into the Academy agent lifecycle."""
from __future__ import annotations

import asyncio
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


class CairnAgentMixin:
    cairn: CairnClient | None = None
    _cairn_config: CairnConfig | None = None
    _cairn_flush_task: asyncio.Task[None] | None = None

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
        transport: httpx.AsyncBaseTransport | None = None,
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

    async def discover(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        if self.cairn is None:
            return []
        return await self.cairn.discover(query, k)
