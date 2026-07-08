"""Append-only JSONL write queue with a batch flusher."""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from .config import CairnConfig
from .entity import ScoreEvent
from .identity import KeyStore

logger = logging.getLogger("academy_cairn")

SubmitBatch = Callable[[list[ScoreEvent]], Awaitable[None]]


class ScoreQueue:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._inflight_path = Path(str(self._path) + ".inflight")

    def enqueue(self, event: ScoreEvent) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as fh:
            fh.write(event.model_dump_json(exclude_none=True) + "\n")

    def _read_file(self, path: Path) -> list[ScoreEvent]:
        if not path.exists():
            return []
        events: list[ScoreEvent] = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(ScoreEvent.model_validate_json(line))
            except Exception as exc:
                logger.warning("skipping corrupt queue line: %s", exc)
        return events

    def read_all(self) -> list[ScoreEvent]:
        # inflight events are older (mid-flush); list them before the live tail.
        return self._read_file(self._inflight_path) + self._read_file(self._path)

    def _write_events(self, path: Path, events: list[ScoreEvent]) -> None:
        content = (
            ""
            if not events
            else "\n".join(
                e.model_dump_json(exclude_none=True) for e in events
            )
            + "\n"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(content)
                fh.flush()
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    def _remove_inflight(self) -> None:
        try:
            self._inflight_path.unlink()
        except FileNotFoundError:
            pass

    def _claim_inflight(self) -> None:
        # Fold any prior crashed-flush leftovers plus the live tail into the
        # inflight file, then clear the live file, all synchronously (between
        # awaits) so a concurrent sync `enqueue()` can never land in a file
        # that is about to be rewritten out from under it.
        old_inflight = self._read_file(self._inflight_path)
        live = self._read_file(self._path)
        combined = old_inflight + live
        self._write_events(self._inflight_path, combined)
        self._write_events(self._path, [])

    async def flush(self, submit_batch: SubmitBatch) -> int:
        self._claim_inflight()
        pending = self._read_file(self._inflight_path)
        flushed = 0
        while pending:
            chunk, pending = pending[:100], pending[100:]
            try:
                await submit_batch(chunk)
            except Exception as exc:
                logger.debug("flush chunk failed, keeping events: %s", exc)
                self._write_events(self._inflight_path, chunk + pending)
                return flushed
            flushed += len(chunk)
            self._write_events(self._inflight_path, pending)  # drop acked lines
        self._remove_inflight()
        return flushed


def _find_key_for_slug(config: CairnConfig, slug: str) -> str | None:
    matches = sorted(config.key_dir.glob(f"*/{slug}.key"))
    if not matches:
        return None
    return matches[0].read_text().strip() or None


async def _flush_queue_file(
    config: CairnConfig,
    file: Path,
    host: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    from .client import CairnClient

    slug = file.stem
    key = _find_key_for_slug(config, slug)
    if key is None:
        logger.warning("no key found for queue file %s; skipping", file)
        return 0
    client = CairnClient(
        config,
        reviewer_id="agent://academy/cli/flush",
        uid="cli00000",
        key_store=KeyStore(config.key_dir, host),
        queue_path=file,
        api_key=key,
        transport=transport,
    )
    try:
        n = await client.flush()
        logger.info("flushed %d events from %s", n, file)
        return n
    except Exception as exc:  # fail-open: one bad file must not stop others
        logger.warning("failed to flush %s: %s", file, exc)
        return 0
    finally:
        await client.aclose()


def main() -> None:
    import asyncio
    import socket

    config = CairnConfig()
    queue_dir = config.key_dir.parent / "queue"
    if not queue_dir.exists():
        logger.info("no queue directory at %s; nothing to flush", queue_dir)
        return
    host = socket.gethostname()

    async def _run() -> None:
        for file in sorted(queue_dir.glob("*.jsonl")):
            await _flush_queue_file(config, file, host)

    asyncio.run(_run())


if __name__ == "__main__":  # python -m academy_cairn.flush maps here via flush.py
    main()
