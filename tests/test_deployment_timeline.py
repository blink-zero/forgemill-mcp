"""Tests for ForgemillClient.get_deployment_timeline."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from forgemill_mcp.client import ForgemillClient


def _client(handler: Any) -> ForgemillClient:
    transport = httpx.MockTransport(handler)
    return ForgemillClient("https://forgemill.example.com", "fm_x", transport=transport)


@pytest.mark.asyncio
async def test_get_deployment_timeline_hits_expected_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/deployments/42/timeline"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=[
                {"timestamp": "2026-08-10T10:00:00Z", "source": "audit", "message": "Deployment requested"},
                {"timestamp": "2026-08-10T10:00:05Z", "source": "log", "message": "provisioning started"},
            ],
        )

    result = await _client(handler).get_deployment_timeline(42)
    assert len(result) == 2
    assert result[0]["source"] == "audit"
    assert result[1]["source"] == "log"


@pytest.mark.asyncio
async def test_get_deployment_timeline_defaults_to_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    result = await _client(handler).get_deployment_timeline(42)
    assert result == []
