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
        transport: httpx.AsyncBaseTransport | None = None,
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
            transport=transport,
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

    # --- Discover & adopt (Forgemill v0.20.0+) -------------------------------

    async def discover_vms(
        self, target_id: int, *, include_ignored: bool = False
    ) -> dict[str, Any]:
        """Live list of VMs on a target that Forgemill doesn't manage
        (templates excluded): target_id, target_name, computed_at, managed,
        unmanaged, ignored counts and vms[] with ref, name, power_state,
        ip_address, cpu, memory_mb, disk_gb, guest_id, host, ignored."""
        params = {"include_ignored": "true"} if include_ignored else {}
        return await self._request("GET", f"/targets/{target_id}/discover", params=params)

    async def list_ignored_vms(self, target_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/targets/{target_id}/ignored") or []

    async def adopt_vms(self, target_id: int, vm_refs: list[str]) -> dict[str, Any]:
        """Take VMs under management by hypervisor ref. Returns adopted[]
        (full VM records) and skipped[] ({ref, reason})."""
        return await self._request("POST", f"/targets/{target_id}/adopt", json={"vm_refs": vm_refs})

    async def ignore_discovered_vms(
        self, target_id: int, vm_refs: list[str], *, names: dict[str, str] | None = None
    ) -> None:
        body: dict[str, Any] = {"vm_refs": vm_refs}
        if names:
            body["names"] = names
        await self._request("POST", f"/targets/{target_id}/ignore", json=body)

    async def unignore_discovered_vms(self, target_id: int, vm_refs: list[str]) -> None:
        await self._request("DELETE", f"/targets/{target_id}/ignore", json={"vm_refs": vm_refs})

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

    async def delete_vm(
        self, vm_id: int, *, force: bool = False, dry_run: bool = False
    ) -> dict[str, Any] | None:
        params = {}
        if force:
            params["force"] = "true"
        if dry_run:
            params["dry_run"] = "true"
        # dry_run responses carry a preview body; a real delete returns 204/None.
        return await self._request("DELETE", f"/vms/{vm_id}", params=params)

    async def sync_vm(self, vm_id: int) -> dict[str, Any]:
        return await self._request("POST", f"/vms/{vm_id}/sync")

    async def sync_all_vms(self, *, dry_run: bool = False) -> dict[str, Any]:
        params = {"dry_run": "true"} if dry_run else {}
        return await self._request("POST", "/vms/sync-all", params=params)

    async def get_vm_credentials(self, vm_id: int) -> dict[str, Any]:
        """The SSH login Forgemill uses for a VM: username, kind
        (password|private_key), source (vm|deployment), password (password
        logins only — a private key or sudo password is never returned),
        has_sudo_password, set_at. 404 when the VM has none
        (adopted/registered VMs until set_vm_credentials)."""
        return await self._request("GET", f"/vms/{vm_id}/credentials")

    @staticmethod
    def _credentials_body(
        username: str, password: str, private_key: str, sudo_password: str, force: bool
    ) -> dict[str, Any]:
        if bool(password) == bool(private_key):
            raise ValueError("provide exactly one of password or private_key")
        body: dict[str, Any] = {"username": username}
        if password:
            body["password"] = password
        else:
            body["private_key"] = private_key
        if sudo_password:
            body["sudo_password"] = sudo_password
        if force:
            body["force"] = True
        return body

    async def set_vm_credentials(
        self,
        vm_id: int,
        username: str,
        *,
        password: str = "",
        private_key: str = "",
        sudo_password: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        """Store an explicit SSH login for a VM (Forgemill v0.20.0+). Exactly
        one of password / private_key (unencrypted PEM or OpenSSH).
        sudo_password is handed to sudo when it asks (needed for key logins
        whose sudo prompts). Forgemill tries the credentials on the VM first
        and refuses (422) ones that can't run actions unless force=True.
        Returns {saved, check}."""
        body = self._credentials_body(username, password, private_key, sudo_password, force)
        return await self._request("PUT", f"/vms/{vm_id}/credentials", json=body)

    async def test_vm_credentials(
        self,
        vm_id: int,
        username: str,
        *,
        password: str = "",
        private_key: str = "",
        sudo_password: str = "",
    ) -> dict[str, Any]:
        """Try credentials on the VM without storing them. Returns the check:
        skipped, ssh_ok, sudo (nopasswd|password|needs_password|
        wrong_password|not_permitted|requiretty|...), ok, message."""
        body = self._credentials_body(username, password, private_key, sudo_password, False)
        return await self._request("POST", f"/vms/{vm_id}/credentials/test", json=body)

    async def clear_vm_credentials(self, vm_id: int) -> None:
        await self._request("DELETE", f"/vms/{vm_id}/credentials")

    async def list_vm_disks(self, vm_id: int) -> list[dict[str, Any]]:
        """Disks live from the hypervisor: key, label, size_gb, datastore,
        provisioning (thin/thick on vSphere; volume format on Proxmox),
        backing, pending?."""
        return await self._request("GET", f"/vms/{vm_id}/disks") or []

    async def add_vm_disk(
        self,
        vm_id: int,
        size_gb: int,
        *,
        datastore: str = "",
        provisioning: str = "",
    ) -> dict[str, Any]:
        """Attach a new, empty virtual disk to a VM.

        datastore and provisioning are left out of the body when empty so
        Forgemill applies the defaults (the VM's first disk's datastore;
        thin on vSphere). Response shape: {"status": "attached", "disk":
        {key, label, size_gb, datastore, provisioning, backing, pending?}}."""
        body: dict[str, Any] = {"size_gb": size_gb}
        if datastore:
            body["datastore"] = datastore
        if provisioning:
            body["provisioning"] = provisioning
        return await self._request("POST", f"/vms/{vm_id}/disks", json=body)

    async def list_vm_events(self, vm_id: int, limit: int = 100) -> list[dict[str, Any]]:
        """A VM's recent operational events (provider warnings, attach
        results), newest first: id, vm_id, level (info|warn|error), message,
        created_at. Forgemill v0.19.1+."""
        return await self._request("GET", f"/vms/{vm_id}/events", params={"limit": limit}) or []

    async def get_diagnostics(self) -> dict[str, Any]:
        """Admin-only operational snapshot (Forgemill v0.19.1+): build info,
        per-target status + last sync result, recent VM warnings/errors,
        recent failed deployments, recent server-side errors and the
        rate-limit rejection count."""
        return await self._request("GET", "/diagnostics")

    async def list_vm_nics(self, vm_id: int) -> list[dict[str, Any]]:
        """Network adapters live from the hypervisor: key, label, adapter_type,
        network, mac_address, connected, vlan_tag?, pending?, addresses[]."""
        return await self._request("GET", f"/vms/{vm_id}/nics") or []

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

    async def add_vm_nic(
        self,
        vm_id: int,
        network: str,
        *,
        adapter_type: str = "",
        connected: bool = True,
        vlan_tag: int | None = None,
    ) -> dict[str, Any]:
        """Attach an additional network adapter to a VM.

        adapter_type is left out of the body when empty so Forgemill applies
        the provider's default (vmxnet3 on vSphere, virtio on Proxmox) rather
        than this client guessing one. vlan_tag is Proxmox-only and omitted
        when None. Response shape: {"status": "attached", "nic": {key, label,
        adapter_type, network, mac_address, connected, vlan_tag?, pending?}}."""
        body: dict[str, Any] = {"network": network, "connected": connected}
        if adapter_type:
            body["adapter_type"] = adapter_type
        if vlan_tag is not None:
            body["vlan_tag"] = vlan_tag
        return await self._request("POST", f"/vms/{vm_id}/nics", json=body)

    # --- Target admin operations ------------------------------------------

    async def test_target(self, target_id: int) -> dict[str, Any]:
        """Run a connection test against a target. Returns { success, message }."""
        return await self._request("POST", f"/targets/{target_id}/test")

    async def sync_target_templates(self, target_id: int) -> dict[str, Any]:
        """Pull the template list from a target into Forgemill's database."""
        return await self._request("POST", f"/targets/{target_id}/sync")

    # --- Actions / executions ---------------------------------------------

    async def list_actions(self, *, include_drafts: bool = False) -> list[dict[str, Any]]:
        """Runnable actions. Drafts (saved, not published, never runnable —
        Forgemill v0.22.0+) are included only when include_drafts is true;
        each action carries status ("active" | "draft") and source
        ("user" | "ai")."""
        params = {"include_drafts": "true"} if include_drafts else {}
        return await self._request("GET", "/actions", params=params) or []

    async def publish_action(self, action_id: int) -> dict[str, Any]:
        """Publish a draft action so it can run (Forgemill v0.22.0+). 409 if
        it is not a draft; 400 if its content would not pass create."""
        return await self._request("POST", f"/actions/{action_id}/publish")

    async def get_action(self, action_id: int) -> dict[str, Any] | None:
        """Forgemill doesn't expose GET /actions/{id} — fetch the list and filter.
        Returns None if no matching action."""
        actions = await self.list_actions()
        for a in actions:
            if int(a.get("id", -1)) == action_id:
                return a
        return None

    async def create_action(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a custom action. Body shape:
        {
          "name": str,
          "description": str,
          "category": "packages" | "scripts" | "security" | "monitoring" | "custom",
          "script": str,                       # bash, max 64KB
          "script_type": "bash",              # optional, defaults to bash
          "platform": "linux",                # optional, defaults to linux
          "parameters": [ActionParameter, ...] # optional
        }
        Built-in actions cannot be created — they ship with Forgemill."""
        return await self._request("POST", "/actions", json=body)

    async def update_action(
        self, action_id: int, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Update an existing custom action. Forgemill rejects updates to
        built-in actions with a 400."""
        return await self._request("PUT", f"/actions/{action_id}", json=body)

    async def delete_action(self, action_id: int) -> dict[str, Any] | None:
        """Delete a custom action. Forgemill rejects deletes of built-in
        actions with a 400. Returns whatever Forgemill responds with (often
        nothing — caller should fall back to a synthesised status)."""
        return await self._request("DELETE", f"/actions/{action_id}")

    async def list_action_versions(self, action_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/actions/{action_id}/versions") or []

    async def get_action_version(self, action_id: int, version: int) -> dict[str, Any]:
        return await self._request("GET", f"/actions/{action_id}/versions/{version}")

    async def rollback_action(self, action_id: int, version: int) -> dict[str, Any]:
        return await self._request("POST", f"/actions/{action_id}/rollback", json={"version": version})

    async def import_actions(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        """Bulk-create actions from a list of exported entries (same body
        shape as create_action, one dict per action). Each entry is validated
        exactly like create_action — a bad entry only fails that entry, the
        rest of the batch still imports. Forgemill caps a single import at
        100 entries. Response shape:
        {"created": int, "failed": int, "results": [{"index", "name",
        "status", "id"?, "error"?}, ...]}"""
        return await self._request("POST", "/actions/import", json={"actions": actions})

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

    async def preview_deploy(self, body: dict[str, Any]) -> dict[str, Any]:
        """Same body shape as deploy_vm, but Forgemill only validates — no VM is created."""
        return await self._request("POST", "/deploy/preflight", json=body)

    async def get_deployment(self, deployment_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/deploy/{deployment_id}")

    async def get_deployment_manifest(self, deployment_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/deployments/{deployment_id}/manifest")

    async def get_deployment_timeline(self, deployment_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/deployments/{deployment_id}/timeline") or []

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
