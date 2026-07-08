"""rated(handle): score peer agents from Handle invocation outcomes."""
from __future__ import annotations

import inspect
import logging
import time
from typing import Any

from .entity import EntityRef, agent_entity
from .rater import rate_outcome

logger = logging.getLogger("academy_cairn")

_MISSING = object()


class RatedHandle:
    """Non-serialized local proxy that rates a wrapped Academy Handle."""

    def __init__(self, handle: Any, *, cairn: Any) -> None:
        object.__setattr__(self, "_handle", handle)
        object.__setattr__(self, "_cairn", cairn)

    def _peer_ref(self) -> EntityRef:
        handle = object.__getattribute__(self, "_handle")
        cairn = object.__getattribute__(self, "_cairn")
        agent_id = getattr(handle, "agent_id", None)
        name = getattr(agent_id, "name", None) or (
            f"anon-{str(getattr(agent_id, 'uid', ''))[:8]}"
        )
        namespace = getattr(getattr(cairn, "config", None), "namespace", "unknown")
        return agent_entity(namespace, name)

    async def action(self, name: str, /, *args: Any, **kwargs: Any) -> Any:
        handle = object.__getattribute__(self, "_handle")
        cairn = object.__getattribute__(self, "_cairn")
        ref = self._peer_ref()
        weight = cairn.config.default_weight
        start = time.monotonic()
        try:
            result = await handle.action(name, *args, **kwargs)
        except Exception as exc:
            try:
                cairn.enqueue(
                    rate_outcome(
                        ref,
                        success=False,
                        elapsed_s=time.monotonic() - start,
                        exc=exc,
                        weight=weight,
                    )
                )
            except Exception as enqueue_exc:  # fail-open: never mask exc
                logger.debug("cairn enqueue failed open: %s", enqueue_exc)
            raise
        try:
            cairn.enqueue(
                rate_outcome(
                    ref,
                    success=True,
                    elapsed_s=time.monotonic() - start,
                    weight=weight,
                )
            )
        except Exception as enqueue_exc:  # fail-open
            logger.debug("cairn enqueue failed open: %s", enqueue_exc)
        return result

    def __getattr__(self, name: str) -> Any:
        handle = object.__getattribute__(self, "_handle")
        if inspect.getattr_static(handle, name, _MISSING) is _MISSING:
            # Not a real attribute -> Academy treats it as a remote action
            # name. Route through the rated action path so attribute-style
            # calls are scored.
            async def rated_call(*args: Any, **kwargs: Any) -> Any:
                return await self.action(name, *args, **kwargs)

            return rated_call
        # Real attribute/method (agent_id, ping, shutdown, ...) -> pass
        # through unwrapped.
        return getattr(handle, name)

    def __reduce__(self) -> tuple[Any, tuple[Any, ...]]:
        # accidental serialization degrades to the plain inner handle
        return (_identity, (object.__getattribute__(self, "_handle"),))


def _identity(handle: Any) -> Any:
    return handle


def rated(handle: Any, *, cairn: Any) -> RatedHandle:
    return RatedHandle(handle, cairn=cairn)
