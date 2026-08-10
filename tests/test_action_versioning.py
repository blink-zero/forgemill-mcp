"""Tests for ForgemillClient's action version history / rollback methods."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from forgemill_mcp.client import ForgemillClient


def _client(handler: Any) -> ForgemillClient:
    transport = httpx.MockTransport(handler)
    return ForgemillClient("https://forgemill.example.com", "fm_x", transport=transport)


@pytest.mark.asyncio
async def test_list_action_versions_hits_expected_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/actions/9/versions"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=[
                {"action_id": 9, "version": 2, "script": "new"},
                {"action_id": 9, "version": 1, "script": "old"},
            ],
        )

    result = await _client(handler).list_action_versions(9)
    assert [v["version"] for v in result] == [2, 1]


@pytest.mark.asyncio
async def test_list_action_versions_defaults_to_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    result = await _client(handler).list_action_versions(9)
    assert result == []


@pytest.mark.asyncio
async def test_get_action_version_hits_expected_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/actions/9/versions/1"
        return httpx.Response(200, json={"action_id": 9, "version": 1, "script": "old"})

    result = await _client(handler).get_action_version(9, 1)
    assert result["version"] == 1


@pytest.mark.asyncio
async def test_rollback_action_posts_target_version() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/actions/9/rollback"
        assert request.method == "POST"
        import json as _json

        assert _json.loads(request.content) == {"version": 1}
        return httpx.Response(200, json={"id": 9, "version": 3, "script": "old"})

    result = await _client(handler).rollback_action(9, 1)
    assert result["version"] == 3
    assert result["script"] == "old"
