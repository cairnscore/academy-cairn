import httpx
import pytest

from academy_cairn.client import CairnClient
from academy_cairn.config import CairnConfig
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
        return httpx.Response(
            200,
            json={
                "composite_score": 0.82,
                "confidence": 0.6,
                "last_updated": "x",
            },
        )

    client = make_client(handler)
    r = await client.get_score(
        EntityRef(type="data_source", external_id="https://a/v1")
    )
    assert (r.composite_score, r.confidence) == (0.82, 0.6)
    await client.aclose()


@pytest.mark.asyncio
async def test_unknown_entity_is_no_data():
    def handler(req):
        return httpx.Response(
            200,
            json={
                "composite_score": 0.5,
                "confidence": 0.0,
                "last_updated": None,
            },
        )

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
