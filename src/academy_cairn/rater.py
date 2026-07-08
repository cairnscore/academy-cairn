"""Map an observed action/handle outcome to a Cairn ScoreEvent (no LLM)."""
from __future__ import annotations

from .entity import EntityRef, ScoreEvent, snake_case


def latency_score(elapsed_s: float) -> float:
    if elapsed_s < 1.0:
        return 1.0
    if elapsed_s < 5.0:
        return 0.7
    return 0.4


def rate_outcome(
    ref: EntityRef,
    *,
    success: bool,
    elapsed_s: float,
    exc: BaseException | None = None,
    weight: float,
    context: str = "general",
) -> ScoreEvent:
    if success:
        return ScoreEvent(
            reviewee=ref,
            score=0.75,
            weight=weight,
            context=context,
            dimensions={"reliability": 1.0, "latency": latency_score(elapsed_s)},
            metrics={"latency_ms": round(elapsed_s * 1000, 1)},
            rationale=f"Automated outcome rating for {ref.external_id}: success.",
        )
    return ScoreEvent(
        reviewee=ref,
        score=0.2,
        weight=weight,
        context=context,
        dimensions={"reliability": 0.0},
        failure_modes=[snake_case(type(exc).__name__)] if exc else ["unknown"],
        rationale=f"Automated outcome rating for {ref.external_id}: failure.",
    )
