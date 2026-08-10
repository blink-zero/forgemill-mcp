"""Tests for ForgemillClient's dry-run / orphan-surfacing additions.

Uses httpx.MockTransport to assert on the exact request made (method, path,
query params) and to control the response, without a live Forgemill server.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from forgemill_mcp.client import ForgemillClient


def _client(handler: Any) -> ForgemillClient:
    transport = httpx.MockTransport(handler)
    return ForgemillClient("https://forgemill.example.com", "fm_x", transport=transport)


@pytest.mark.asyncio
async def test_delete_vm_default_sends_no_params() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(204)

    result = await _client(handler).delete_vm(42)
    assert seen["params"] == {}
    assert result is None


@pytest.mark.asyncio
async def test_delete_vm_dry_run_returns_preview_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == {"dry_run": "true"}
        return httpx.Response(
            200,
            json={
                "vm_id": 42,
                "force": False,
                "would_delete_on_hypervisor": True,
                "would_untrack_only": False,
                "dependent_snapshots": 1,
                "dependent_executions": 0,
            },
        )

    result = await _client(handler).delete_vm(42, dry_run=True)
    assert result == {
        "vm_id": 42,
        "force": False,
        "would_delete_on_hypervisor": True,
        "would_untrack_only": False,
        "dependent_snapshots": 1,
        "dependent_executions": 0,
    }


@pytest.mark.asyncio
async def test_delete_vm_force_and_dry_run_combine() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == {"force": "true", "dry_run": "true"}
        return httpx.Response(200, json={"would_untrack_only": True})

    await _client(handler).delete_vm(42, force=True, dry_run=True)


@pytest.mark.asyncio
async def test_sync_all_vms_default_unchanged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == {}
        return httpx.Response(200, json={"synced": 3, "orphaned": 0})

    result = await _client(handler).sync_all_vms()
    assert result == {"synced": 3, "orphaned": 0}


@pytest.mark.asyncio
async def test_sync_all_vms_dry_run_passes_flag_and_surfaces_orphans() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == {"dry_run": "true"}
        return httpx.Response(
            200,
            json={
                "synced": 2,
                "orphaned": 1,
                "orphaned_vms": [
                    {"id": 7, "vm_name": "web-01", "vm_ref": "vm-100", "target_id": 1}
                ],
            },
        )

    result = await _client(handler).sync_all_vms(dry_run=True)
    assert result["orphaned_vms"] == [
        {"id": 7, "vm_name": "web-01", "vm_ref": "vm-100", "target_id": 1}
    ]
