"""Tests for ForgemillClient.get_deployment_manifest."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from forgemill_mcp.client import ForgemillClient


def _client(handler: Any) -> ForgemillClient:
    transport = httpx.MockTransport(handler)
    return ForgemillClient("https://forgemill.example.com", "fm_x", transport=transport)


@pytest.mark.asyncio
async def test_get_deployment_manifest_hits_expected_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/deployments/42/manifest"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "deployment_id": 42,
                "what": 'Deploy VM "web-01" from template "ubuntu-22.04" onto target "esxi-prod"',
                "status": "completed",
                "has_credentials": True,
                "credentials_ref": "GET /vms/7/credentials",
                "undo_options": [
                    "Preview delete: DELETE /vms/7?dry_run=true",
                    "Delete VM from hypervisor: DELETE /vms/7",
                ],
            },
        )

    result = await _client(handler).get_deployment_manifest(42)
    assert result["deployment_id"] == 42
    assert result["credentials_ref"] == "GET /vms/7/credentials"
    assert len(result["undo_options"]) == 2
