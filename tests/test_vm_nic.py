"""Tests for the add_vm_nic client method and MCP tool registration.

The client tests pin the exact request Forgemill receives (path, method,
body) with httpx.MockTransport. The server tests build a real FastMCP
instance and check the registered tool set, so a refactor that silently
drops an existing tool — or registers a mutating one in read-only mode —
fails here rather than in someone's agent session.
"""

from __future__ import annotations

import json as _json
from typing import Any

import httpx
import pytest

from forgemill_mcp.client import ForgemillClient, ForgemillError
from forgemill_mcp.config import Settings
from forgemill_mcp.server import build_server


def _client(handler: Any) -> ForgemillClient:
    transport = httpx.MockTransport(handler)
    return ForgemillClient("https://forgemill.example.com", "fm_x", transport=transport)


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


_ATTACHED = {
    "status": "attached",
    "nic": {
        "key": 4001,
        "label": "Network adapter 2",
        "adapter_type": "vmxnet3",
        "network": "VM Network",
        "mac_address": "00:50:56:aa:bb:cc",
        "connected": True,
    },
}


# --- client -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_vm_nic_posts_minimal_body_and_omits_default_adapter() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = _json.loads(request.content)
        return httpx.Response(201, json=_ATTACHED)

    result = await _client(handler).add_vm_nic(42, "VM Network")
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/vms/42/nics"
    # adapter_type is deliberately absent so Forgemill applies its own default.
    assert seen["body"] == {"network": "VM Network", "connected": True}
    assert result == _ATTACHED


@pytest.mark.asyncio
async def test_add_vm_nic_passes_explicit_adapter_and_connected_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert _json.loads(request.content) == {
            "network": "/DC1/network/dvPG-Backend",
            "connected": False,
            "adapter_type": "e1000e",
        }
        return httpx.Response(201, json=_ATTACHED)

    await _client(handler).add_vm_nic(
        42, "/DC1/network/dvPG-Backend", adapter_type="e1000e", connected=False
    )


@pytest.mark.asyncio
async def test_add_vm_nic_vm_not_found_raises_with_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "VM not found"})

    with pytest.raises(ForgemillError) as exc:
        await _client(handler).add_vm_nic(99999, "VM Network")
    assert exc.value.status_code == 404
    assert "VM not found" in exc.value.message


@pytest.mark.asyncio
async def test_add_vm_nic_invalid_network_surfaces_forgemill_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": 'network not found: "nope"'})

    with pytest.raises(ForgemillError) as exc:
        await _client(handler).add_vm_nic(42, "nope")
    assert exc.value.status_code == 400
    assert "network not found" in exc.value.message


@pytest.mark.asyncio
async def test_add_vm_nic_unsupported_provider_surfaces_forgemill_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": "operation not supported by this provider: adding a "
                "network adapter is not available for Proxmox VE targets"
            },
        )

    with pytest.raises(ForgemillError) as exc:
        await _client(handler).add_vm_nic(7, "vmbr0")
    assert exc.value.status_code == 400
    assert "Proxmox" in exc.value.message


# --- server tool registry ----------------------------------------------------


# A representative slice of the tool surface that must survive any change to
# server.py. Not exhaustive on purpose — it's a tripwire, not a schema.
_READ_TOOLS = {
    "server_version",
    "dashboard_summary",
    "list_targets",
    "get_target_resources",
    "list_templates",
    "list_vms",
    "get_vm",
    "list_vm_disks",
    "list_actions",
    "export_actions",
    "list_history",
}
_MUTATING_TOOLS = {
    "power_vm",
    "sync_vm",
    "resize_vm",
    "expand_vm_disk",
    "add_vm_nic",
    "create_snapshot",
    "delete_vm",
    "execute_action",
    "deploy_vm",
    "preview_deploy",
    "import_actions",
}


async def _tool_names(*, allow_mutations: bool) -> set[str]:
    client = _client(lambda request: httpx.Response(200, json={}))
    try:
        mcp = build_server(_settings(allow_mutations=allow_mutations), client)
        return {t.name for t in await mcp.list_tools()}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_add_vm_nic_registered_alongside_existing_mutating_tools() -> None:
    names = await _tool_names(allow_mutations=True)
    missing = (_READ_TOOLS | _MUTATING_TOOLS) - names
    assert not missing, f"tools missing from the mutating server: {sorted(missing)}"


@pytest.mark.asyncio
async def test_add_vm_nic_absent_in_read_only_mode() -> None:
    names = await _tool_names(allow_mutations=False)
    assert _READ_TOOLS <= names
    leaked = _MUTATING_TOOLS & names
    assert not leaked, f"mutating tools registered in read-only mode: {sorted(leaked)}"


@pytest.mark.asyncio
async def test_add_vm_nic_tool_schema_exposes_expected_parameters() -> None:
    client = _client(lambda request: httpx.Response(200, json={}))
    try:
        mcp = build_server(_settings(allow_mutations=True), client)
        tool = await mcp.get_tool("add_vm_nic")
    finally:
        await client.close()
    assert tool is not None
    props = tool.parameters["properties"]
    assert set(props) == {"vm_id", "network", "adapter_type", "connected"}
    assert set(tool.parameters.get("required", [])) == {"vm_id", "network"}
    assert props["adapter_type"]["default"] == ""
    assert props["connected"]["default"] is True
    # The description is what an agent reads to decide how to call it.
    assert "vSphere" in (tool.description or "")
    assert "vmxnet3" in (tool.description or "")
