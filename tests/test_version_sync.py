"""forgemill-mcp and Forgemill share major.minor; the server must say so."""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest

from forgemill_mcp import __version__
from forgemill_mcp.client import ForgemillClient
from forgemill_mcp.config import Settings
from forgemill_mcp.server import build_server, compatibility_warning


def test_package_version_is_a_real_version() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


@pytest.mark.parametrize(
    ("mcp", "server", "warn"),
    [
        ("0.20.0", "0.20.0", False),
        ("0.20.0", "0.20.3", False),
        ("0.20.0", "v0.20.1-rc1", False),
        ("0.20.0", "0.19.1", True),
        ("0.20.0", "0.21.0", True),
        ("0.20.0", "1.20.0", True),
        ("0.20.0", "dev", False),
        ("0.20.0", "", False),
    ],
)
def test_compatibility_warning_on_major_minor_mismatch_only(mcp: str, server: str, warn: bool) -> None:
    w = compatibility_warning(mcp, server)
    assert (w is not None) is warn, w
    if warn:
        assert mcp in w and server in w


@pytest.mark.asyncio
async def test_server_version_tool_reports_both_sides_and_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/version"
        return httpx.Response(200, json={"version": "0.1.0", "commit": "abc", "date": "d"})

    client = ForgemillClient("https://forgemill.example.com", "fm_x", transport=httpx.MockTransport(handler))
    settings = Settings(
        forgemill_url="https://forgemill.example.com", forgemill_api_key="fm_x", verify_tls=True,
        allow_mutations=False, mcp_port=3030, mcp_host="127.0.0.1", mcp_auth_token=None, request_timeout_seconds=5.0,
    )
    try:
        mcp = build_server(settings, client)
        out: Any = await mcp.call_tool("server_version", {})
        text = out[0].text if isinstance(out, list) else out.content[0].text
    finally:
        await client.close()
    assert f'"forgemill_mcp": "{__version__}"' in text
    assert '"commit": "abc"' in text
    assert "version mismatch" in text
