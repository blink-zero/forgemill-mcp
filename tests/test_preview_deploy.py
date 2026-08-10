"""Tests for ForgemillClient.preview_deploy."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from forgemill_mcp.client import ForgemillClient


def _client(handler: Any) -> ForgemillClient:
    transport = httpx.MockTransport(handler)
    return ForgemillClient("https://forgemill.example.com", "fm_x", transport=transport)


@pytest.mark.asyncio
async def test_preview_deploy_hits_preflight_path_with_same_body_shape() -> None:
    sent_body: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/deploy/preflight"
        assert request.method == "POST"
        import json as _json

        sent_body.update(_json.loads(request.content))
        return httpx.Response(200, json={"valid": True})

    body = {"template_id": 1, "target_id": 2, "vm_name": "web-01", "cpu": 2, "memory_mb": 2048}
    result = await _client(handler).preview_deploy(body)
    assert result["valid"] is True
    assert sent_body == body


@pytest.mark.asyncio
async def test_preview_deploy_surfaces_blockers_and_warnings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "valid": False,
                "blockers": ['a VM named "web-01" already exists on this target (tracked by Forgemill)'],
                "warnings": ["could not verify target resources: connect: dial tcp: timeout"],
            },
        )

    body = {"template_id": 1, "target_id": 2, "vm_name": "web-01", "cpu": 2, "memory_mb": 2048}
    result = await _client(handler).preview_deploy(body)
    assert result["valid"] is False
    assert len(result["blockers"]) == 1
    assert len(result["warnings"]) == 1
