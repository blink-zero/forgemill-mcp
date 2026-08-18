"""Tests for action import/export: ForgemillClient.import_actions and the
export-shaping helpers used by the export_actions tool.
"""

from __future__ import annotations

import json as _json
from typing import Any

import httpx
import pytest

from forgemill_mcp.client import ForgemillClient
from forgemill_mcp.server import _build_export_file, _to_export_entry


def _client(handler: Any) -> ForgemillClient:
    transport = httpx.MockTransport(handler)
    return ForgemillClient("https://forgemill.example.com", "fm_x", transport=transport)


@pytest.mark.asyncio
async def test_import_actions_posts_expected_path_and_body() -> None:
    entries = [{"name": "a", "script": "echo hi"}]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/actions/import"
        assert request.method == "POST"
        assert _json.loads(request.content) == {"actions": entries}
        return httpx.Response(
            200,
            json={
                "created": 1,
                "failed": 0,
                "results": [{"index": 0, "name": "a", "status": "created", "id": 7}],
            },
        )

    result = await _client(handler).import_actions(entries)
    assert result["created"] == 1
    assert result["failed"] == 0
    assert result["results"][0]["id"] == 7


@pytest.mark.asyncio
async def test_import_actions_reports_partial_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "created": 1,
                "failed": 1,
                "results": [
                    {"index": 0, "name": "good", "status": "created", "id": 1},
                    {"index": 1, "name": "bad", "status": "failed", "error": "name and script are required"},
                ],
            },
        )

    result = await _client(handler).import_actions(
        [{"name": "good", "script": "echo hi"}, {"name": "bad", "script": ""}]
    )
    assert result["created"] == 1
    assert result["failed"] == 1
    assert result["results"][1]["error"] == "name and script are required"


def test_to_export_entry_keeps_only_export_fields() -> None:
    action = {
        "id": 5,
        "name": "Install Nginx",
        "description": "installs nginx",
        "category": "packages",
        "script": "apt-get install -y nginx",
        "script_type": "bash",
        "platform": "linux",
        "parameters": [],
        "tags": ["nginx"],
        "builtin": False,
        "version": 3,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }
    entry = _to_export_entry(action)
    assert entry == {
        "name": "Install Nginx",
        "description": "installs nginx",
        "category": "packages",
        "script": "apt-get install -y nginx",
        "script_type": "bash",
        "platform": "linux",
        "parameters": [],
        "tags": ["nginx"],
    }
    assert "id" not in entry
    assert "builtin" not in entry
    assert "version" not in entry


def test_build_export_file_wraps_entries_with_schema_metadata() -> None:
    file = _build_export_file([{"id": 1, "name": "a", "script": "echo hi"}])
    assert file["schema_version"] == 1
    assert file["source"] == "forgemill"
    assert isinstance(file["exported_at"], str) and file["exported_at"]
    assert file["actions"] == [
        {
            "name": "a",
            "description": None,
            "category": None,
            "script": "echo hi",
            "script_type": None,
            "platform": None,
            "parameters": None,
            "tags": None,
        }
    ]
