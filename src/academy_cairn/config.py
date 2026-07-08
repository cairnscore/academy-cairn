"""Configuration for academy-cairn (env prefix CAIRN_)."""
from __future__ import annotations

import socket
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_namespace() -> str:
    return socket.gethostname() or "localhost"


def _default_key_dir() -> Path:
    return Path.home() / ".cairn" / "academy" / "keys"


class CairnConfig(BaseSettings):
    """Runtime configuration, read from CAIRN_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="CAIRN_", extra="ignore")

    base_url: str = "https://api.cairnscore.ai"
    namespace: str = Field(default_factory=_default_namespace)
    key_dir: Path = Field(default_factory=_default_key_dir)
    default_weight: float = 0.3
    timeout_s: float = 5.0
    enabled: bool = True
    flush_interval_s: float = 60.0
    offline: bool = False
