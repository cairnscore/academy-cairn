import pytest

from academy_cairn.entity import EntityRef, ScoreEvent
from academy_cairn.queue import ScoreQueue


def _event(i):
    return ScoreEvent(
        reviewee=EntityRef(type="data_source", external_id=f"https://a/{i}"), score=0.5
    )


def test_enqueue_appends_lines(tmp_path):
    q = ScoreQueue(tmp_path / "q.jsonl")
    q.enqueue(_event(0))
    q.enqueue(_event(1))
    assert len(q.read_all()) == 2


def test_read_all_skips_corrupt_lines(tmp_path):
    path = tmp_path / "q.jsonl"
    q = ScoreQueue(path)
    q.enqueue(_event(0))
    with path.open("a") as fh:
        fh.write("{ this is not json\n")
    q.enqueue(_event(1))
    assert len(q.read_all()) == 2  # corrupt line skipped, valid ones kept


@pytest.mark.asyncio
async def test_flush_drains_in_batches_and_empties(tmp_path):
    q = ScoreQueue(tmp_path / "q.jsonl")
    for i in range(150):
        q.enqueue(_event(i))
    sizes = []
    async def fake_submit(events):
        sizes.append(len(events))
    n = await q.flush(fake_submit)
    assert n == 150
    assert sizes == [100, 50]
    assert q.read_all() == []  # fully drained


@pytest.mark.asyncio
async def test_flush_keeps_events_when_submit_fails(tmp_path):
    q = ScoreQueue(tmp_path / "q.jsonl")
    q.enqueue(_event(0))
    async def failing_submit(events):
        raise RuntimeError("network down")
    n = await q.flush(failing_submit)
    assert n == 0
    assert len(q.read_all()) == 1  # nothing lost on failure
