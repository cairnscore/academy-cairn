"""Optional mixin that wires a CairnClient into the Academy agent lifecycle.

Not required: ``@cairn_guarded`` and ``rated(...)`` self-provision a client from
the agent's identity on first use (see ``provision.py``). Use this mixin when you
want the client created eagerly on startup with a background flusher, rather than
lazily on first use.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from .client import CairnClient
from .config import CairnConfig
from .provision import _flush_loop, build_client


class CairnAgentMixin:
    cairn: CairnClient | None = None
    _cairn_config: CairnConfig | None = None
    _cairn_flush_task: asyncio.Task[None] | None = None

    def _config(self) -> CairnConfig:
        if self._cairn_config is None:
            self._cairn_config = CairnConfig()
        return self._cairn_config

    async def agent_on_startup(self) -> None:
        config = self._config()
        if config.enabled:
            agent_id = getattr(self, "agent_id", None)
            name = getattr(agent_id, "name", None)
            uid = str(getattr(agent_id, "uid", "00000000"))
            self.cairn = build_client(config, name=name, uid=uid)
            if not config.offline:
                self._cairn_flush_task = asyncio.create_task(
                    _flush_loop(self.cairn, config.flush_interval_s),
                )
        parent_startup = getattr(super(), "agent_on_startup", None)
        if parent_startup is not None:
            await parent_startup()

    async def agent_on_shutdown(self) -> None:
        if self._cairn_flush_task is not None:
            self._cairn_flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cairn_flush_task
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
