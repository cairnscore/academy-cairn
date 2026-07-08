import httpx
import pytest

from academy_cairn.config import CairnConfig
from academy_cairn.entity import EntityRef, ScoreEvent
from academy_cairn.identity import KeyStore
from academy_cairn.queue import ScoreQueue, _flush_queue_file


def _event(i):
    return ScoreEvent(
        reviewee=EntityRef(type="data_source", external_id=f"https://a/{i}"), score=0.5
    )


@pytest.mark.asyncio
async def test_flush_queue_file_drains_real_agent_queue_using_ondisk_key(tmp_path):
    key_dir = tmp_path / "keys"
    queue_dir = tmp_path / "queue"
    host = "node01"
    slug = "academy_argus_triage_deadbeef"

    KeyStore(key_dir, host).save(slug, "tg_ondisk")

    queue_path = queue_dir / f"{slug}.jsonl"
    q = ScoreQueue(queue_path)
    q.enqueue(_event(0))
    q.enqueue(_event(1))

    mint_calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/keys":
            mint_calls["n"] += 1
            return httpx.Response(200, json={"api_key": "tg_minted"})
        assert req.headers.get("X-Api-Key") == "tg_ondisk"
        return httpx.Response(200, json={"count": 0, "reviewees": []})

    config = CairnConfig(key_dir=key_dir)
    n = await _flush_queue_file(
        config, queue_path, host, transport=httpx.MockTransport(handler)
    )

    assert n == 2
    assert mint_calls["n"] == 0  # used the on-disk key, never minted
    assert ScoreQueue(queue_path).read_all() == []  # queue file drained


@pytest.mark.asyncio
async def test_flush_queue_file_skips_when_no_key_found(tmp_path):
    key_dir = tmp_path / "keys"
    queue_dir = tmp_path / "queue"
    slug = "unknown_reviewer_00000000"

    queue_path = queue_dir / f"{slug}.jsonl"
    q = ScoreQueue(queue_path)
    q.enqueue(_event(0))

    def handler(req: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not make any HTTP call without a key")

    config = CairnConfig(key_dir=key_dir)
    n = await _flush_queue_file(
        config, queue_path, "node01", transport=httpx.MockTransport(handler)
    )

    assert n == 0
    assert len(ScoreQueue(queue_path).read_all()) == 1  # untouched, nothing lost
