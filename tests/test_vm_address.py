"""set_vm_address: the manual address for VMs without a guest agent (Forgemill v0.24.0+)."""

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
async def test_set_vm_address_puts_address_and_clears_with_empty_string() -> None:
    calls: list[tuple[str, str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = httpx.Response(200, content=request.read()).json()
        calls.append((request.method, request.url.path, body))
        return httpx.Response(200, json={"id": 10, "ip_address": "", "address_override": body["address"]})

    c = _client(handler)
    res = await c.set_vm_address(10, "10.20.40.18")
    assert res["address_override"] == "10.20.40.18"
    await c.set_vm_address(10, "")
    assert calls == [
        ("PUT", "/api/vms/10/address", {"address": "10.20.40.18"}),
        ("PUT", "/api/vms/10/address", {"address": ""}),
    ]


@pytest.mark.asyncio
async def test_set_vm_address_surfaces_forgemill_validation_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "address must be an IPv4/IPv6 address or a hostname"})

    with pytest.raises(ForgemillError) as ei:
        await _client(handler).set_vm_address(10, "ssh://10.0.0.5")
    assert ei.value.status_code == 400 and "hostname" in str(ei.value)


@pytest.mark.asyncio
async def test_execute_refusal_reason_is_in_the_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "Forgemill doesn't know this VM's address. ...", "code": "no_address"})

    with pytest.raises(ForgemillError) as ei:
        await _client(handler).execute_action(10, script="echo hi")
    assert "doesn't know this VM's address" in str(ei.value)


@pytest.mark.asyncio
async def test_set_vm_address_registered_only_when_mutations_are_allowed() -> None:
    c = _client(lambda r: httpx.Response(200, json={}))
    try:
        ro = build_server(_settings(allow_mutations=False), c)
        rw = build_server(_settings(allow_mutations=True), c)
        assert "set_vm_address" not in {t.name for t in await ro.list_tools()}
        tool = await rw.get_tool("set_vm_address")
    finally:
        await c.close()
    assert tool is not None
    assert set(tool.parameters["properties"]) == {"vm_id", "address"}
    assert set(tool.parameters.get("required", [])) == {"vm_id", "address"}
    desc = tool.description or ""
    assert "guest agent" in desc and "sync_vm" in desc and '""' in desc
