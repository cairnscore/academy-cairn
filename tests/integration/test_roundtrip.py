import os
import uuid

import pytest

from academy_cairn.client import CairnClient
from academy_cairn.config import CairnConfig
from academy_cairn.entity import EntityRef, ScoreEvent
from academy_cairn.identity import KeyStore

pytestmark = pytest.mark.skipif(
    not os.environ.get("CAIRN_TEST_URL"), reason="set CAIRN_TEST_URL to run",
)


@pytest.mark.asyncio
async def test_mint_write_read(tmp_path):
    base = os.environ["CAIRN_TEST_URL"]
    reviewer = f"agent://academy/itest/{uuid.uuid4().hex[:8]}"
    ext = f"https://itest.example/{uuid.uuid4().hex[:8]}"
    client = CairnClient(
        CairnConfig(base_url=base),
        reviewer_id=reviewer, uid=uuid.uuid4().hex,
        key_store=KeyStore(tmp_path, host="itest"),
        queue_path=tmp_path / "q.jsonl",
    )
    ref = EntityRef(type="data_source", external_id=ext)
    before = await client.get_score(ref)
    assert before.confidence == 0.0  # unknown entity
    await client.submit(ScoreEvent(reviewee=ref, score=0.9))
    after = await client.get_score(ref)
    assert after.confidence > 0.0  # evidence now recorded
    await client.aclose()
