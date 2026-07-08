"""Append-only JSONL write queue with a batch flusher."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Awaitable, Callable

from .config import CairnConfig
from .entity import ScoreEvent
from .identity import (
    KeyStore,
    agent_name_from,
    identity_slug,
    reviewer_external_id,
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
        config,
        reviewer_id=reviewer,
        uid="cli00000",
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
