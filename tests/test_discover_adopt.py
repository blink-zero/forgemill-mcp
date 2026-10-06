"""Tests for discover/adopt and per-VM credential tools (Forgemill v0.20.0+)."""

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
async def test_discover_vms_path_and_include_ignored_flag() -> None:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.url.params.get("include_ignored")))
        return httpx.Response(200, json={"target_id": 1, "unmanaged": 1, "vms": [{"ref": "vm-9", "name": "x", "ignored": False}]})

    c = _client(handler)
    res = await c.discover_vms(1)
    assert res["vms"][0]["ref"] == "vm-9"
    await c.discover_vms(1, include_ignored=True)
    assert seen == [("/api/targets/1/discover", None), ("/api/targets/1/discover", "true")]


@pytest.mark.asyncio
async def test_adopt_ignore_unignore_send_refs() -> None:
    calls: list[tuple[str, str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        calls.append((request.method, request.url.path, httpx.Response(200, content=body).json() if body else None))
        if request.url.path.endswith("/adopt"):
            return httpx.Response(201, json={"adopted": [{"id": 7, "origin": "adopted"}], "skipped": [{"ref": "vm-1", "reason": "already managed"}]})
        return httpx.Response(204)

    c = _client(handler)
    res = await c.adopt_vms(3, ["vm-9", "vm-1"])
    assert res["adopted"][0]["id"] == 7 and res["skipped"][0]["reason"] == "already managed"
    assert await c.ignore_discovered_vms(3, ["vm-2"], names={"vm-2": "appliance"}) is None
    assert await c.unignore_discovered_vms(3, ["vm-2"]) is None
    assert calls == [
        ("POST", "/api/targets/3/adopt", {"vm_refs": ["vm-9", "vm-1"]}),
        ("POST", "/api/targets/3/ignore", {"vm_refs": ["vm-2"], "names": {"vm-2": "appliance"}}),
        ("DELETE", "/api/targets/3/ignore", {"vm_refs": ["vm-2"]}),
    ]


@pytest.mark.asyncio
async def test_set_vm_credentials_sends_exactly_one_secret_plus_sudo_and_force() -> None:
    bodies: list[dict[str, Any]] = []
    check = {"skipped": False, "ssh_ok": True, "sudo": "password", "ok": True, "message": "ok"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT" and request.url.path == "/api/vms/5/credentials"
        bodies.append(httpx.Response(200, content=request.read()).json())
        return httpx.Response(200, json={"saved": True, "check": check})

    c = _client(handler)
    res = await c.set_vm_credentials(5, "root", password="pw")
    assert res["check"]["sudo"] == "password"
    await c.set_vm_credentials(5, "ops", private_key="-----BEGIN OPENSSH PRIVATE KEY-----\nabc", sudo_password="s", force=True)
    assert bodies == [
        {"username": "root", "password": "pw"},
        {"username": "ops", "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\nabc", "sudo_password": "s", "force": True},
    ]


@pytest.mark.asyncio
async def test_test_vm_credentials_posts_to_test_and_refused_set_surfaces_422() -> None:
    check = {"skipped": False, "ssh_ok": True, "sudo": "needs_password", "ok": False, "message": "SSH login succeeded, but ..."}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/credentials/test"):
            assert request.method == "POST"
            assert httpx.Response(200, content=request.read()).json() == {"username": "u", "private_key": "k"}
            return httpx.Response(200, json=check)
        return httpx.Response(422, json={"error": check["message"], "check": check})

    c = _client(handler)
    assert (await c.test_vm_credentials(5, "u", private_key="k"))["sudo"] == "needs_password"
    with pytest.raises(ForgemillError) as exc:
        await c.set_vm_credentials(5, "u", private_key="k")
    assert exc.value.status_code == 422 and "SSH login succeeded" in str(exc.value)
    with pytest.raises(ValueError):
        await c.set_vm_credentials(5, "root")
    with pytest.raises(ValueError):
        await c.set_vm_credentials(5, "root", password="a", private_key="b")


@pytest.mark.asyncio
async def test_clear_vm_credentials_and_forbidden_surfaces_status() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE" and request.url.path == "/api/vms/5/credentials"
        return httpx.Response(204)

    assert await _client(ok).clear_vm_credentials(5) is None

    def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "insufficient permissions"})

    with pytest.raises(ForgemillError) as exc:
        await _client(forbidden).adopt_vms(1, ["vm-9"])
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_discover_tools_read_only_and_adopt_tools_gated() -> None:
    read = {"discover_vms", "list_ignored_vms"}
    write = {"adopt_vms", "ignore_discovered_vms", "unignore_discovered_vms", "set_vm_credentials", "test_vm_credentials", "clear_vm_credentials"}
    for allow in (True, False):
        client = _client(lambda r: httpx.Response(200, json={}))
        try:
            mcp = build_server(_settings(allow_mutations=allow), client)
            names = {t.name for t in await mcp.list_tools()}
        finally:
            await client.close()
        assert read <= names
        assert (write <= names) is allow, f"allow_mutations={allow}: {sorted(names & write)}"


@pytest.mark.asyncio
async def test_list_vms_origin_filter() -> None:
    vms = [{"id": 1, "origin": "adopted"}, {"id": 2}, {"id": 3, "origin": "registered"}]
    client = _client(lambda r: httpx.Response(200, json=vms))
    try:
        mcp = build_server(_settings(allow_mutations=False), client)
        out = await mcp.call_tool("list_vms", {"origin": "adopted"})
        text = out[0].text if isinstance(out, list) else out.content[0].text
        assert '"id": 1' in text and '"id": 2' not in text
        out = await mcp.call_tool("list_vms", {"origin": "deployed"})
        text = out[0].text if isinstance(out, list) else out.content[0].text
        assert '"id": 2' in text and '"id": 1' not in text
    finally:
        await client.close()
