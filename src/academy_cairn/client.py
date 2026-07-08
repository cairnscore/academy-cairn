"""Async Cairn API client (one httpx transport per agent)."""
from __future__ import annotations

import logging
from typing import Any, cast

import httpx

from .config import CairnConfig
from .entity import EntityRef, Reading, ScoreEvent
from .identity import identity_slug

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

    async def rank(
        self, capability_tag: str, rank_by: str, k: int = 5
    ) -> dict[str, Any]:
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

    async def _mint(self, reviewer_id: str) -> httpx.Response:
        return await self._http.post(
            "/v1/keys", json={"reviewer_external_id": reviewer_id}
        )

    async def _ensure_key(self) -> str | None:
        if self._api_key is not None:
            return self._api_key
        slug = identity_slug(self._reviewer_id)
        if self._keys is not None:
            cached = self._keys.load(slug)
            if cached:
                self._api_key = cached
                return cast(str, cached)
        try:
            resp = await self._mint(self._reviewer_id)
            if resp.status_code == 409:
                self._reviewer_id = f"{self._reviewer_id}-{self._uid[:8]}"
                logger.warning(
                    "cairn identity claimed; retrying as %s", self._reviewer_id
                )
                slug = identity_slug(self._reviewer_id)
                resp = await self._mint(self._reviewer_id)
            resp.raise_for_status()
            key = cast(str, resp.json()["api_key"])
            self._api_key = key
            if self._keys is not None:
                self._keys.save(slug, key)
            return key
        except Exception as exc:  # fail-open
            logger.debug("cairn mint failed: %s", exc)
            return None

    async def submit(self, event: ScoreEvent) -> None:
        if self.config.offline:
            return
        key = await self._ensure_key()
        if key is None:
            return
        try:
            resp = await self._http.post(
                "/v1/scores", json=event.to_payload(), headers={"X-Api-Key": key},
            )
            resp.raise_for_status()
        except Exception as exc:  # fail-open
            logger.debug("cairn submit failed: %s", exc)

    async def submit_batch(self, events: list[ScoreEvent]) -> None:
        if self.config.offline or not events:
            return
        key = await self._ensure_key()
        if key is None:
            return
        for start in range(0, len(events), 100):
            chunk = events[start : start + 100]
            try:
                resp = await self._http.post(
                    "/v1/scores/batch",
                    json={"events": [e.to_payload() for e in chunk]},
                    headers={"X-Api-Key": key},
                )
                resp.raise_for_status()
            except Exception as exc:  # fail-open
                logger.debug("cairn submit_batch chunk failed: %s", exc)
