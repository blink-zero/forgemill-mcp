"""Environment-driven configuration for the Forgemill MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings, all sourced from environment variables."""

    forgemill_url: str
    forgemill_api_key: str
    verify_tls: bool
    allow_mutations: bool
    mcp_port: int
    mcp_host: str
    mcp_auth_token: str | None
    request_timeout_seconds: float

    @classmethod
    def from_env(cls) -> Settings:
        url = os.environ.get("FORGEMILL_URL", "").rstrip("/")
        api_key = os.environ.get("FORGEMILL_API_KEY", "")

        if not url:
            raise RuntimeError(
                "FORGEMILL_URL is required (e.g. https://forgemill.example.com)"
            )
        if not api_key:
            raise RuntimeError(
                "FORGEMILL_API_KEY is required. Generate one in Settings → API Keys."
            )

        return cls(
            forgemill_url=url,
            forgemill_api_key=api_key,
            verify_tls=_bool_env("FORGEMILL_VERIFY_TLS", default=True),
            allow_mutations=_bool_env("FORGEMILL_MCP_ALLOW_MUTATIONS", default=False),
            mcp_port=_int_env("FORGEMILL_MCP_PORT", 3030),
            mcp_host=os.environ.get("FORGEMILL_MCP_HOST", "0.0.0.0"),
            mcp_auth_token=os.environ.get("FORGEMILL_MCP_AUTH_TOKEN") or None,
            request_timeout_seconds=float(
                os.environ.get("FORGEMILL_REQUEST_TIMEOUT", "30")
            ),
        )
