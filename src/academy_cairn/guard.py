"""@cairn_guarded: pre-check trust, run the action, post-rate the outcome."""
from __future__ import annotations

import functools
import inspect
import logging
import time
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel

from .entity import EntityRef, EntityType, Reading
from .rater import rate_outcome

logger = logging.getLogger("academy_cairn")


class TrustPolicy(BaseModel):
    min_score: float = 0.4
    min_confidence: float = 0.3
    on_low: Literal["log", "warn", "block"] = "log"


class CairnTrustError(RuntimeError):
    def __init__(self, ref: EntityRef, reading: Reading) -> None:
        super().__init__(
            f"Cairn policy blocked {ref.external_id} "
            f"(score={reading.composite_score})"
        )
        self.ref = ref
        self.reading = reading


def _resolve_ref(
    entity_type: EntityType,
    id_from: str | Callable[..., object],
    sig: inspect.Signature,
    self_obj: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> EntityRef | None:
    try:
        if callable(id_from):
            result = id_from(self_obj, *args, **kwargs)
            if isinstance(result, EntityRef):
                return result
            return EntityRef(type=entity_type, external_id=str(result))
        bound = sig.bind(self_obj, *args, **kwargs)
        bound.apply_defaults()
        value = bound.arguments[id_from]
        return EntityRef(type=entity_type, external_id=str(value))
    except Exception as exc:  # fail-open: can't resolve ⇒ skip guarding
        logger.debug("cairn could not resolve entity ref: %s", exc)
        return None


async def _pre_check(cairn: Any, ref: EntityRef, policy: TrustPolicy) -> None:
    reading = await cairn.get_score(ref)
    if reading.confidence < policy.min_confidence:
        return  # no data ⇒ always proceed
    if reading.composite_score >= policy.min_score:
        return
    if policy.on_low == "block":
        raise CairnTrustError(ref, reading)
    log = logger.warning if policy.on_low == "warn" else logger.info
    log(
        "cairn low-trust %s score=%.2f conf=%.2f",
        ref.external_id,
        reading.composite_score,
        reading.confidence,
    )


def cairn_guarded(
    *,
    type: EntityType,
    id_from: str | Callable[..., object],
    policy: TrustPolicy | None = None,
    rate: bool = True,
    context: str = "general",
    weight: float | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    the_policy = policy or TrustPolicy()

    def decorator(
        fn: Callable[..., Awaitable[Any]],
    ) -> Callable[..., Awaitable[Any]]:
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            cairn = getattr(self, "cairn", None)
            ref = (
                _resolve_ref(type, id_from, sig, self, args, kwargs)
                if cairn is not None
                else None
            )
            if cairn is not None and ref is not None:
                try:
                    await _pre_check(cairn, ref, the_policy)
                except CairnTrustError:
                    raise
                except Exception as exc:  # fail-open on Cairn errors
                    logger.debug("cairn pre-check failed open: %s", exc)
            start = time.monotonic()
            try:
                result = await fn(self, *args, **kwargs)
            except Exception as exc:
                if cairn is not None and ref is not None and rate:
                    w = weight if weight is not None else cairn.config.default_weight
                    cairn.enqueue(
                        rate_outcome(
                            ref,
                            success=False,
                            elapsed_s=time.monotonic() - start,
                            exc=exc,
                            weight=w,
                            context=context,
                        )
                    )
                raise
            if cairn is not None and ref is not None and rate:
                w = weight if weight is not None else cairn.config.default_weight
                cairn.enqueue(
                    rate_outcome(
                        ref,
                        success=True,
                        elapsed_s=time.monotonic() - start,
                        weight=w,
                        context=context,
                    )
                )
            return result

        return wrapper

    return decorator
