"""Reviewer identity strings and the on-disk claim-once key store."""
from __future__ import annotations

import os
import re
from pathlib import Path


def reviewer_external_id(namespace: str, agent_name: str) -> str:
    return f"agent://academy/{namespace}/{agent_name}"


def agent_name_from(name: str | None, uid: str) -> str:
    return name if name else f"anon-{uid[:8]}"


def identity_slug(reviewer_id: str) -> str:
    body = reviewer_id.replace("agent://", "")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", body).strip("_").lower()
    return slug


class KeyStore:
    """Persists minted API keys, one file per reviewer identity, mode 0600."""

    def __init__(self, key_dir: Path, host: str) -> None:
        self._dir = Path(key_dir) / host

    def _path(self, slug: str) -> Path:
        return self._dir / f"{slug}.key"

    def load(self, slug: str) -> str | None:
        path = self._path(slug)
        if not path.exists():
            return None
        return path.read_text().strip() or None

    def save(self, slug: str, key: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path(slug)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(key)
        path.chmod(0o600)  # ensure 0600 even if the file pre-existed with looser mode
