"""Drafts are hidden from list_actions unless asked; publish_action posts to /publish."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from forgemill_mcp.client import ForgemillClient, ForgemillError
from forgemill_mcp.config import Settings
from forgemill_mcp.server import build_server


def _client(handler: Any) -> ForgemillClient:
    return ForgemillClient("https://forgemill.example.com", "fm_x", transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_list_actions_include_drafts_flag_and_publish() -> None:
    seen: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.url.params.get("include_drafts")))
        if request.url.path.endswith("/publish"):
            return httpx.Response(200, json={"id": 9, "status": "active", "version": 1})
        return httpx.Response(200, json=[{"id": 1, "status": "active"}])

    c = _client(handler)
    await c.list_actions()
    await c.list_actions(include_drafts=True)
    res = await c.publish_action(9)
    assert res["status"] == "active"
    assert seen == [("GET", "/api/actions", None), ("GET", "/api/actions", "true"), ("POST", "/api/actions/9/publish", None)]

    def not_draft(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": "action is not a draft"})

    with pytest.raises(ForgemillError) as exc:
        await _client(not_draft).publish_action(1)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_publish_action_is_gated() -> None:
    for allow in (True, False):
        client = _client(lambda r: httpx.Response(200, json=[]))
        try:
            mcp = build_server(Settings(forgemill_url="https://forgemill.example.com", forgemill_api_key="fm_x", verify_tls=True, allow_mutations=allow, mcp_port=3030, mcp_host="127.0.0.1", mcp_auth_token=None, request_timeout_seconds=5.0), client)
            names = {t.name for t in await mcp.list_tools()}
        finally:
            await client.close()
        assert "list_actions" in names
        assert ("publish_action" in names) is allow
