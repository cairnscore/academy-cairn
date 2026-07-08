import httpx
import pytest

from academy_cairn.config import CairnConfig
from academy_cairn.mixin import CairnAgentMixin


def _handler(req):
    if req.url.path == "/v1/discover":
        return httpx.Response(200, json={"results": [{"entity": {"external_id": "mcp://x"}}]})
    return httpx.Response(200, json={})


@pytest.mark.asyncio
async def test_build_client_uses_identity(tmp_path):
    m = CairnAgentMixin()
    client = m._build_client(
        CairnConfig(namespace="argus", key_dir=tmp_path),
        name="triage", uid="uid00000000",
        transport=httpx.MockTransport(_handler),
    )
    assert client._reviewer_id == "agent://academy/argus/triage"
    await client.aclose()


@pytest.mark.asyncio
async def test_disabled_config_yields_no_client():
    m = CairnAgentMixin()
    m._cairn_config = CairnConfig(enabled=False)
    m.agent_id = type("A", (), {"uid": "u", "name": "n"})()
    # startup with disabled config leaves self.cairn None and does not raise
    await CairnAgentMixin.agent_on_startup(m)
    assert m.cairn is None
