"""Smoke tests for the env-driven settings loader."""

from __future__ import annotations

import os

import pytest

from forgemill_mcp.config import Settings


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("FORGEMILL_"):
            monkeypatch.delenv(key, raising=False)


def test_requires_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("FORGEMILL_API_KEY", "fm_x")
    with pytest.raises(RuntimeError, match="FORGEMILL_URL"):
        Settings.from_env()


def test_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("FORGEMILL_URL", "https://forgemill.example.com")
    with pytest.raises(RuntimeError, match="FORGEMILL_API_KEY"):
        Settings.from_env()


def test_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("FORGEMILL_URL", "https://forgemill.example.com/")
    monkeypatch.setenv("FORGEMILL_API_KEY", "fm_x")
    s = Settings.from_env()
    assert s.forgemill_url == "https://forgemill.example.com"


def test_mutations_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("FORGEMILL_URL", "https://x")
    monkeypatch.setenv("FORGEMILL_API_KEY", "fm_x")
    s = Settings.from_env()
    assert s.allow_mutations is False


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
def test_mutations_parses_truthy(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("FORGEMILL_URL", "https://x")
    monkeypatch.setenv("FORGEMILL_API_KEY", "fm_x")
    monkeypatch.setenv("FORGEMILL_MCP_ALLOW_MUTATIONS", raw)
    s = Settings.from_env()
    assert s.allow_mutations is True


def test_port_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("FORGEMILL_URL", "https://x")
    monkeypatch.setenv("FORGEMILL_API_KEY", "fm_x")
    s = Settings.from_env()
    assert s.mcp_port == 3030


def test_port_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("FORGEMILL_URL", "https://x")
    monkeypatch.setenv("FORGEMILL_API_KEY", "fm_x")
    monkeypatch.setenv("FORGEMILL_MCP_PORT", "9090")
    s = Settings.from_env()
    assert s.mcp_port == 9090
