from academy_cairn.entity import EntityRef
from academy_cairn.rater import latency_score, rate_outcome

REF = EntityRef(type="data_source", external_id="https://a/v1")


def test_latency_score_bands():
    assert latency_score(0.5) == 1.0
    assert latency_score(3.0) == 0.7
    assert latency_score(9.0) == 0.4


def test_success_event():
    ev = rate_outcome(REF, success=True, elapsed_s=0.5, weight=0.3)
    assert ev.score == 0.75
    assert ev.dimensions == {"reliability": 1.0, "latency": 1.0}
    assert ev.metrics["latency_ms"] == 500.0
    assert ev.weight == 0.3
    assert "https://a/v1" in ev.rationale


def test_failure_event_uses_exception_class():
    ev = rate_outcome(REF, success=False, elapsed_s=2.0, exc=TimeoutError(), weight=0.3)
    assert ev.score == 0.2
    assert ev.dimensions == {"reliability": 0.0}
    assert ev.failure_modes == ["timeout_error"]


def test_rationale_never_leaks_args():
    # rationale must only ever contain the entity id, never other values
    ev = rate_outcome(REF, success=True, elapsed_s=0.1, weight=0.3)
    assert ev.rationale.count("https://a/v1") == 1
