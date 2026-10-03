"""Tests for list_vm_events / get_diagnostics (read-only tools)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from forgemill_mcp.client import ForgemillClient, ForgemillError
from forgemill_mcp.config import Settings
from forgemill_mcp.server import build_server


def _client(handler: Any) -> ForgemillClient:
    return ForgemillClient("https://forgemill.example.com", "fm_x", transport=httpx.MockTransport(handler))


def _settings(*, allow_mutations: bool) -> Settings:
    return Settings(
        forgemill_url="https://forgemill.example.com",
        forgemill_api_key="fm_x",
        verify_tls=True,
        allow_mutations=allow_mutations,
        mcp_port=3030,
        mcp_host="127.0.0.1",
        mcp_auth_token=None,
        request_timeout_seconds=5.0,
    )


@pytest.mark.asyncio
async def test_list_vm_events_gets_path_with_limit() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["limit"] = request.url.params.get("limit")
        return httpx.Response(200, json=[{"id": 1, "vm_id": 42, "level": "warn", "message": "x", "created_at": "2026-10-03T00:00:00Z"}])

    events = await _client(handler).list_vm_events(42, limit=25)
    assert seen["path"] == "/api/vms/42/events"
    assert seen["limit"] == "25"
    assert events[0]["level"] == "warn"


@pytest.mark.asyncio
async def test_list_vm_events_null_body_is_empty_list() -> None:
    assert await _client(lambda r: httpx.Response(200, content=b"null")).list_vm_events(42) == []


@pytest.mark.asyncio
async def test_get_diagnostics_gets_path_and_surfaces_forbidden() -> None:
    payload = {"build": {"version": "0.19.1"}, "targets": [], "rate_limited_requests": 3}

    def ok(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/diagnostics"
        return httpx.Response(200, json=payload)

    assert await _client(ok).get_diagnostics() == payload

    def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "admin role required"})

    with pytest.raises(ForgemillError) as exc:
        await _client(forbidden).get_diagnostics()
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_diagnostics_tools_are_read_only_and_always_registered() -> None:
    for allow in (True, False):
        client = _client(lambda r: httpx.Response(200, json={}))
        try:
            mcp = build_server(_settings(allow_mutations=allow), client)
            names = {t.name for t in await mcp.list_tools()}
        finally:
            await client.close()
        assert {"list_vm_events", "get_diagnostics"} <= names, f"allow_mutations={allow}: {sorted(names)}"
