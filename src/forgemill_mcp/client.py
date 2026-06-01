"""Async Forgemill REST API client used by the MCP tools.

Thin wrapper around httpx that handles auth, base URL, and common error
shapes. Each method maps directly to one Forgemill endpoint — tools call
into here without doing their own HTTP plumbing.
"""

from __future__ import annotations

from typing import Any

import httpx


class ForgemillError(RuntimeError):
    """Raised when Forgemill returns a non-2xx response."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Forgemill API {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class ForgemillClient:
    """Async client for the Forgemill REST API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        verify: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "forgemill-mcp/0.1",
            },
            verify=verify,
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # --- Internal -----------------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        path = path if path.startswith("/") else f"/{path}"
        resp = await self._client.request(method, f"/api{path}", **kwargs)
        if resp.status_code >= 400:
            try:
                body = resp.json()
                msg = body.get("error") or body.get("message") or resp.text
            except Exception:
                msg = resp.text or resp.reason_phrase
            raise ForgemillError(resp.status_code, msg)
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except Exception:
            return resp.text

    # --- Targets ------------------------------------------------------------

    async def list_targets(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/targets") or []

    async def get_target(self, target_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/targets/{target_id}")

    async def get_target_resources(self, target_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/targets/{target_id}/resources")

    # --- Templates ----------------------------------------------------------

    async def list_templates(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/templates") or []

    async def get_template(self, template_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/templates/{template_id}")

    # --- VMs ----------------------------------------------------------------

    async def list_vms(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/vms") or []

    async def get_vm(self, vm_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/vms/{vm_id}")

    async def list_vm_snapshots(self, vm_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/vms/{vm_id}/snapshots") or []

    async def list_vm_executions(self, vm_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/vms/{vm_id}/executions") or []

    async def get_vm_console_url(self, vm_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/vms/{vm_id}/console")

    # Mutations -- gated by config.

    async def power_vm(self, vm_id: int, action: str) -> dict[str, Any]:
        if action not in {"start", "stop", "restart", "suspend"}:
            raise ValueError(f"Invalid power action: {action!r}")
        return await self._request("POST", f"/vms/{vm_id}/power/{action}")

    async def create_snapshot(
        self, vm_id: int, name: str, description: str = "", memory: bool = False
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/vms/{vm_id}/snapshots",
            json={"name": name, "description": description, "memory": memory},
        )

    async def revert_snapshot(self, vm_id: int, snap_id: int) -> dict[str, Any]:
        return await self._request(
            "POST", f"/vms/{vm_id}/snapshots/{snap_id}/revert"
        )

    async def delete_snapshot(self, vm_id: int, snap_id: int) -> None:
        await self._request("DELETE", f"/vms/{vm_id}/snapshots/{snap_id}")

    async def delete_vm(self, vm_id: int, *, force: bool = False) -> None:
        params = {"force": "true"} if force else {}
        await self._request("DELETE", f"/vms/{vm_id}", params=params)

    async def sync_vm(self, vm_id: int) -> dict[str, Any]:
        return await self._request("POST", f"/vms/{vm_id}/sync")

    async def sync_all_vms(self) -> dict[str, Any]:
        return await self._request("POST", "/vms/sync-all")

    async def get_vm_credentials(self, vm_id: int) -> dict[str, Any]:
        """Reveal the deploy-time credentials for a VM. Admin only on Forgemill side."""
        return await self._request("GET", f"/vms/{vm_id}/credentials")

    async def list_vm_disks(self, vm_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/vms/{vm_id}/disks") or []

    async def resize_vm(self, vm_id: int, cpu: int, memory_mb: int) -> dict[str, Any]:
        return await self._request(
            "PUT", f"/vms/{vm_id}/resize", json={"cpu": cpu, "memory_mb": memory_mb}
        )

    async def expand_vm_disk(
        self, vm_id: int, disk_key: int, new_size_gb: int
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"/vms/{vm_id}/disks/{disk_key}/expand",
            json={"new_size_gb": new_size_gb},
        )

    # --- Target admin operations ------------------------------------------

    async def test_target(self, target_id: int) -> dict[str, Any]:
        """Run a connection test against a target. Returns { success, message }."""
        return await self._request("POST", f"/targets/{target_id}/test")

    async def sync_target_templates(self, target_id: int) -> dict[str, Any]:
        """Pull the template list from a target into Forgemill's database."""
        return await self._request("POST", f"/targets/{target_id}/sync")

    # --- Actions / executions ---------------------------------------------

    async def list_actions(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/actions") or []

    async def execute_action(
        self,
        vm_id: int,
        *,
        action_id: int | None = None,
        script: str | None = None,
        parameter_values: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if action_id is not None:
            body["action_id"] = action_id
        if script is not None:
            body["script"] = script
        if parameter_values:
            body["parameter_values"] = parameter_values
        if timeout_seconds is not None:
            body["timeout_seconds"] = timeout_seconds
        return await self._request("POST", f"/vms/{vm_id}/execute", json=body)

    async def get_execution(self, execution_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/executions/{execution_id}")

    async def cancel_execution(self, execution_id: int) -> dict[str, Any]:
        return await self._request("POST", f"/executions/{execution_id}/cancel")

    # --- Blueprints --------------------------------------------------------

    async def list_blueprints(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/blueprints") or []

    async def deploy_blueprint(
        self, blueprint_id: int, *, vm_name: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/blueprints/{blueprint_id}/deploy",
            json={"vm_name": vm_name},
        )

    # --- Deploy ------------------------------------------------------------

    async def deploy_vm(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/deploy", json=body)

    async def get_deployment(self, deployment_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/deploy/{deployment_id}")

    # --- History ----------------------------------------------------------

    async def list_history(
        self,
        *,
        page: int = 1,
        per_page: int = 25,
        status: str | None = None,
        target_id: int | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if status:
            params["status"] = status
        if target_id:
            params["target_id"] = target_id
        if search:
            params["search"] = search
        return await self._request("GET", "/history", params=params)

    # --- Notifications ----------------------------------------------------

    async def list_notifications(
        self, *, unread_only: bool = False, limit: int = 50
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if unread_only:
            params["unread_only"] = "true"
        return await self._request("GET", "/notifications", params=params)

    # --- Dashboard / version ----------------------------------------------

    async def dashboard(self) -> dict[str, Any]:
        return await self._request("GET", "/dashboard")

    async def version(self) -> dict[str, Any]:
        return await self._request("GET", "/version")
