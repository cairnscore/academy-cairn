from academy_cairn.entity import (
    EntityRef,
    Reading,
    ScoreEvent,
    agent_entity,
    snake_case,
)


def test_reading_no_data():
    r = Reading.no_data()
    assert (r.composite_score, r.confidence, r.last_updated) == (0.5, 0.0, None)
    assert r.profile_url is None


def test_reading_captures_profile_url():
    r = Reading.model_validate(
        {
            "composite_score": 0.8,
            "confidence": 0.5,
            "profile_url": "https://cairnscore.ai/p/data_source/https%3A%2F%2Fa",
        }
    )
    assert r.profile_url == "https://cairnscore.ai/p/data_source/https%3A%2F%2Fa"


def test_score_event_payload_drops_none():
    ev = ScoreEvent(
        reviewee=EntityRef(type="data_source", external_id="https://a.example/v1"),
        score=0.75,
        dimensions={"reliability": 1.0},
    )
    payload = ev.to_payload()
    assert payload["reviewee"] == {"type": "data_source", "external_id": "https://a.example/v1"}
    assert payload["score"] == 0.75
    assert payload["context"] == "general"
    assert payload["dimensions"] == {"reliability": 1.0}
    assert "rationale" not in payload  # None fields dropped
    assert "weight" not in payload


def test_agent_entity_formula():
    ref = agent_entity("argus", "triage")
    assert ref.type == "agent"
    assert ref.external_id == "agent://academy/argus/triage"


def test_snake_case():
    assert snake_case("TimeoutError") == "timeout_error"
    assert snake_case("HTTPError") == "http_error"
    assert snake_case("ValueError") == "value_error"
