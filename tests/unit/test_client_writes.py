import httpx
import pytest

from academy_cairn.client import CairnClient
from academy_cairn.config import CairnConfig
from academy_cairn.entity import EntityRef, ScoreEvent
from academy_cairn.identity import KeyStore


def _event(i=0):
    return ScoreEvent(
        reviewee=EntityRef(type="data_source", external_id=f"https://a/{i}"),
        score=0.75,
    )


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
                return httpx.Response(
                    409, json={"error": {"code": "conflict", "message": "claimed"}}
                )
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


@pytest.mark.asyncio
async def test_client_flush_fails_open_on_queue_error(tmp_path):
    def handler(req):
        return httpx.Response(200, json={"count": 0, "reviewees": []})
    client = CairnClient(
        CairnConfig(),
        reviewer_id="agent://academy/test/agent",
        uid="uid00000000",
        key_store=KeyStore(tmp_path / "keys", host="node01"),
        transport=httpx.MockTransport(handler),
        queue_path=tmp_path / "queue" / "q.jsonl",
    )

    async def broken_flush(_submit_batch):
        raise OSError("disk full")

    client._queue.flush = broken_flush  # type: ignore[method-assign]
    n = await client.flush()
    assert n == 0  # fail-open: no raise
    await client.aclose()
