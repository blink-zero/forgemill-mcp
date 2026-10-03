"""Tests for the add_vm_disk client method and MCP tool registration — the
disk sibling of test_vm_nic.py."""

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
    "disk": {
        "key": 2001,
        "label": "Hard disk 2",
        "size_gb": 20,
        "datastore": "ds-nvme-01",
        "provisioning": "thin",
        "backing": "[ds-nvme-01] web-01/web-01_1.vmdk",
    },
}


# --- client -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_vm_disk_posts_minimal_body_and_omits_defaults() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = _json.loads(request.content)
        return httpx.Response(201, json=_ATTACHED)

    result = await _client(handler).add_vm_disk(42, 20)
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/vms/42/disks"
    # datastore / provisioning absent so Forgemill applies its own defaults.
    assert seen["body"] == {"size_gb": 20}
    assert result == _ATTACHED


@pytest.mark.asyncio
async def test_add_vm_disk_passes_datastore_and_provisioning_when_given() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = _json.loads(request.content)
        return httpx.Response(201, json=_ATTACHED)

    await _client(handler).add_vm_disk(42, 50, datastore="ds-sata-01", provisioning="thick")
    assert seen["body"] == {"size_gb": 50, "datastore": "ds-sata-01", "provisioning": "thick"}


@pytest.mark.asyncio
async def test_add_vm_disk_errors_surface_forgemill_message_and_status() -> None:
    def not_found(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "VM not found"})

    with pytest.raises(ForgemillError) as exc:
        await _client(not_found).add_vm_disk(999, 10)
    assert exc.value.status_code == 404

    def bad_datastore(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": 'datastore not found: "nope"'})

    with pytest.raises(ForgemillError) as exc:
        await _client(bad_datastore).add_vm_disk(42, 10, datastore="nope")
    assert exc.value.status_code == 400
    assert "datastore not found" in exc.value.message

    def no_provisioning(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": "invalid disk request: provisioning cannot be chosen per disk on Proxmox targets — the storage decides"},
        )

    with pytest.raises(ForgemillError) as exc:
        await _client(no_provisioning).add_vm_disk(42, 10, provisioning="thin")
    assert "storage decides" in exc.value.message


@pytest.mark.asyncio
async def test_list_vm_disks_returns_rich_fields() -> None:
    disks = [
        {"key": 2000, "label": "Hard disk 1", "size_gb": 40, "datastore": "ds-nvme-01", "provisioning": "thin", "backing": "[ds-nvme-01] web-01/web-01.vmdk"},
        {"key": 1, "label": "scsi1", "size_gb": 10, "datastore": "local-zfs", "backing": "local-zfs:vm-100-disk-1", "pending": True},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/vms/42/disks"
        return httpx.Response(200, json=disks)

    assert await _client(handler).list_vm_disks(42) == disks


# --- server -----------------------------------------------------------------


async def _tool_names(*, allow_mutations: bool) -> set[str]:
    client = _client(lambda request: httpx.Response(500))
    mcp = build_server(_settings(allow_mutations=allow_mutations), client)
    return {t.name for t in await mcp.list_tools()}


@pytest.mark.asyncio
async def test_add_vm_disk_registered_only_when_mutations_are_allowed() -> None:
    names = await _tool_names(allow_mutations=True)
    assert {"add_vm_disk", "list_vm_disks", "expand_vm_disk", "add_vm_nic"} <= names

    read_only = await _tool_names(allow_mutations=False)
    assert "list_vm_disks" in read_only
    assert "add_vm_disk" not in read_only


@pytest.mark.asyncio
async def test_add_vm_disk_tool_schema_exposes_expected_parameters() -> None:
    client = _client(lambda request: httpx.Response(200, json={}))
    try:
        mcp = build_server(_settings(allow_mutations=True), client)
        tool = await mcp.get_tool("add_vm_disk")
    finally:
        await client.close()
    assert tool is not None
    props = tool.parameters["properties"]
    assert set(props) == {"vm_id", "size_gb", "datastore", "provisioning"}
    assert set(tool.parameters.get("required", [])) == {"vm_id", "size_gb"}
    assert props["datastore"]["default"] == ""
    assert props["provisioning"]["default"] == ""
    desc = tool.description or ""
    assert "vSphere" in desc and "Proxmox" in desc
    assert "thin" in desc and "pending" in desc and "expand_vm_disk" in desc
