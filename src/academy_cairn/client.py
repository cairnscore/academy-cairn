"""Async Cairn API client (one httpx transport per agent)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import CairnConfig
from .entity import EntityRef, Reading

logger = logging.getLogger("academy_cairn")


class CairnClient:
    def __init__(
        self,
        config: CairnConfig,
        *,
        reviewer_id: str,
        uid: str,
        key_store: Any,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._reviewer_id = reviewer_id
        self._uid = uid
        self._keys = key_store
        self._api_key: str | None = None
        self._http = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout_s,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_score(self, ref: EntityRef) -> Reading:
        if self.config.offline:
            return Reading.no_data()
        try:
            resp = await self._http.get(
                "/v1/score",
                params={"type": ref.type, "external_id": ref.external_id},
            )
            resp.raise_for_status()
            return Reading.model_validate(resp.json())
        except Exception as exc:  # fail-open
            logger.debug("cairn get_score failed for %s: %s", ref.external_id, exc)
            return Reading.no_data()

    async def read_batch(self, refs: list[EntityRef]) -> dict[str, Reading]:
        if self.config.offline or not refs:
            return {r.external_id: Reading.no_data() for r in refs}
        try:
            resp = await self._http.post(
                "/v1/score/batch",
                json={"refs": [r.model_dump() for r in refs]},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                item["external_id"]: Reading.model_validate(item)
                for item in data
            }
        except Exception as exc:  # fail-open
            logger.debug("cairn read_batch failed: %s", exc)
            return {r.external_id: Reading.no_data() for r in refs}

    async def get_profile(self, ref: EntityRef) -> dict[str, Any]:
        if self.config.offline:
            return {}
        try:
            resp = await self._http.get(
                "/v1/profile",
                params={"type": ref.type, "external_id": ref.external_id},
            )
            resp.raise_for_status()
            result = resp.json()
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # fail-open
            logger.debug("cairn get_profile failed: %s", exc)
            return {}

    async def discover(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        if self.config.offline:
            return []
        try:
            resp = await self._http.post("/v1/discover", json={"query": query, "k": k})
            resp.raise_for_status()
            result = resp.json()
            return result.get("results", []) if isinstance(result, dict) else []
        except Exception as exc:  # fail-open
            logger.debug("cairn discover failed: %s", exc)
            return []

    async def rank(self, capability_tag: str, rank_by: str, k: int = 5) -> dict[str, Any]:
        if self.config.offline:
            return {}
        try:
            resp = await self._http.post(
                "/v1/rank",
                json={"capability_tag": capability_tag, "rank_by": rank_by, "k": k},
            )
            resp.raise_for_status()
            result = resp.json()
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # fail-open
            logger.debug("cairn rank failed: %s", exc)
            return {}
