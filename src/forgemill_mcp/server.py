"""Forgemill MCP server entrypoint.

Exposes the Forgemill REST API as MCP tools so Claude (and any other
MCP-compatible client) can query and operate against a Forgemill
deployment. The mutating tool set is gated behind
FORGEMILL_MCP_ALLOW_MUTATIONS so the server runs read-only by default.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp import FastMCP

from .client import ForgemillClient, ForgemillError
from .config import Settings

logger = logging.getLogger("forgemill_mcp")


def _dump(payload: Any) -> str:
    """Stable JSON serialisation for tool return values."""

    return json.dumps(payload, indent=2, default=str, sort_keys=True)


def build_server(settings: Settings, client: ForgemillClient) -> FastMCP:
    """Build a FastMCP server with read-only tools and, if enabled, mutating tools."""

    mcp: FastMCP = FastMCP(
        name="forgemill",
        instructions=(
            "Forgemill manages VM lifecycle across vCenter, ESXi standalone, and "
            "Proxmox VE hypervisors. Use the read tools (list_*, get_*) to inspect "
            "current state. When the user asks for a status overview, prefer "
            "dashboard_summary or list_vms with filters over making many small calls."
        ),
    )

    # --- Read-only tools --------------------------------------------------

    @mcp.tool()
    async def server_version() -> str:
        """Return the version and commit of the connected Forgemill server."""
        try:
            return _dump(await client.version())
        except ForgemillError as e:
            return f"error: {e}"

    @mcp.tool()
    async def dashboard_summary() -> str:
        """Top-level counts (targets, templates, VMs, actions) plus recent activity."""
        return _dump(await client.dashboard())

    @mcp.tool()
    async def list_targets() -> str:
        """List configured hypervisor targets (vCenter / ESXi / Proxmox)."""
        return _dump(await client.list_targets())

    @mcp.tool()
    async def get_target(target_id: int) -> str:
        """Get a target's full details by ID."""
        return _dump(await client.get_target(target_id))

    @mcp.tool()
    async def get_target_resources(target_id: int) -> str:
        """Return the resource inventory of a target — datastores, networks,
        folders, resource pools — as the hypervisor reports them."""
        return _dump(await client.get_target_resources(target_id))

    @mcp.tool()
    async def list_templates() -> str:
        """List VM templates synced from your hypervisors."""
        return _dump(await client.list_templates())

    @mcp.tool()
    async def get_template(template_id: int) -> str:
        """Get a template's full details by ID."""
        return _dump(await client.get_template(template_id))

    @mcp.tool()
    async def list_vms(
        power_state: str | None = None,
        target_name: str | None = None,
        os_match: str | None = None,
    ) -> str:
        """List managed VMs. Optionally filter by power_state (e.g. 'poweredOn',
        'poweredOff', 'suspended'), target name, or substring match on os_type."""
        vms = await client.list_vms()
        if power_state:
            vms = [v for v in vms if v.get("power_state") == power_state]
        if target_name:
            vms = [v for v in vms if v.get("target_name") == target_name]
        if os_match:
            needle = os_match.lower()
            vms = [v for v in vms if needle in (v.get("os_type") or "").lower()]
        return _dump(vms)

    @mcp.tool()
    async def get_vm(vm_id: int) -> str:
        """Get a VM's full record by ID."""
        return _dump(await client.get_vm(vm_id))

    @mcp.tool()
    async def list_vm_snapshots(vm_id: int) -> str:
        """List snapshots for a VM."""
        return _dump(await client.list_vm_snapshots(vm_id))

    @mcp.tool()
    async def list_vm_executions(vm_id: int) -> str:
        """List action-execution history for a VM."""
        return _dump(await client.list_vm_executions(vm_id))

    @mcp.tool()
    async def get_vm_console_url(vm_id: int) -> str:
        """Return the hypervisor-native console URL for a VM (VMRC for vSphere,
        noVNC for Proxmox). Admin-only on the Forgemill side — will 403 if the
        API key is for a non-admin user."""
        return _dump(await client.get_vm_console_url(vm_id))

    @mcp.tool()
    async def list_vm_disks(vm_id: int) -> str:
        """List the disks attached to a VM as the hypervisor reports them."""
        return _dump(await client.list_vm_disks(vm_id))

    @mcp.tool()
    async def list_actions() -> str:
        """List available post-deploy actions (built-in and custom)."""
        return _dump(await client.list_actions())

    @mcp.tool()
    async def get_action(action_id: int) -> str:
        """Return a single action's full record — name, category, script, and
        parameter schema — by ID. Returns an empty object if no match."""
        action = await client.get_action(action_id)
        return _dump(action) if action is not None else "{}"

    @mcp.tool()
    async def get_execution(execution_id: int) -> str:
        """Get a single action execution with full output."""
        return _dump(await client.get_execution(execution_id))

    @mcp.tool()
    async def list_blueprints() -> str:
        """List saved deployment blueprints."""
        return _dump(await client.list_blueprints())

    @mcp.tool()
    async def list_history(
        page: int = 1,
        per_page: int = 25,
        status: str | None = None,
        target_id: int | None = None,
        search: str | None = None,
    ) -> str:
        """Paginated deployment history. Filter by status (completed/running/failed/
        cancelled/pending), target_id, or free-text search across name/template/target."""
        return _dump(
            await client.list_history(
                page=page,
                per_page=per_page,
                status=status,
                target_id=target_id,
                search=search,
            )
        )

    @mcp.tool()
    async def list_notifications(unread_only: bool = False, limit: int = 50) -> str:
        """List the calling user's in-app notifications."""
        return _dump(
            await client.list_notifications(unread_only=unread_only, limit=limit)
        )

    # --- Mutating tools (registered only when explicitly enabled) -------

    if settings.allow_mutations:
        logger.warning(
            "FORGEMILL_MCP_ALLOW_MUTATIONS is enabled — write tools are registered."
        )

        @mcp.tool()
        async def power_vm(vm_id: int, action: str) -> str:
            """Power operation on a VM. action must be one of: start, stop, restart, suspend."""
            return _dump(await client.power_vm(vm_id, action))

        @mcp.tool()
        async def sync_vm(vm_id: int) -> str:
            """Force an immediate refresh of a single VM's state from its hypervisor."""
            return _dump(await client.sync_vm(vm_id))

        @mcp.tool()
        async def sync_all_vms(dry_run: bool = False) -> str:
            """Force an immediate refresh of every VM's state from its hypervisor.

            Any VM the hypervisor no longer reports is untracked from Forgemill —
            the response's orphaned_vms lists exactly which ones (id/name/ref).
            Pass dry_run=True to see what would be untracked without removing
            anything."""
            return _dump(await client.sync_all_vms(dry_run=dry_run))

        @mcp.tool()
        async def test_target(target_id: int) -> str:
            """Run a connection test against a target. Returns { success, message }
            so even a failed test is a valid response — don't treat false as an error."""
            return _dump(await client.test_target(target_id))

        @mcp.tool()
        async def sync_target_templates(target_id: int) -> str:
            """Pull the latest template inventory from a target into Forgemill's
            local database."""
            return _dump(await client.sync_target_templates(target_id))

        @mcp.tool()
        async def get_vm_credentials(vm_id: int) -> str:
            """Reveal the deploy-time SSH credentials for a VM (username + password
            decrypted on demand). Sensitive — the API call is audit-logged."""
            return _dump(await client.get_vm_credentials(vm_id))

        @mcp.tool()
        async def resize_vm(vm_id: int, cpu: int, memory_mb: int) -> str:
            """Resize a VM's CPU count and memory. VM may need to be powered off
            first depending on the hypervisor and hot-add settings."""
            return _dump(await client.resize_vm(vm_id, cpu, memory_mb))

        @mcp.tool()
        async def expand_vm_disk(
            vm_id: int, disk_key: int, new_size_gb: int
        ) -> str:
            """Expand a specific VM disk to a larger size. Cannot shrink. The
            disk_key comes from list_vm_disks."""
            return _dump(await client.expand_vm_disk(vm_id, disk_key, new_size_gb))

        @mcp.tool()
        async def create_snapshot(
            vm_id: int, name: str, description: str = "", memory: bool = False
        ) -> str:
            """Create a snapshot of a VM. Set memory=True to include guest RAM state."""
            return _dump(
                await client.create_snapshot(
                    vm_id, name=name, description=description, memory=memory
                )
            )

        @mcp.tool()
        async def revert_snapshot(vm_id: int, snapshot_id: int) -> str:
            """Revert a VM to a previous snapshot. The VM's current state is lost."""
            return _dump(await client.revert_snapshot(vm_id, snapshot_id))

        @mcp.tool()
        async def delete_snapshot(vm_id: int, snapshot_id: int) -> str:
            """Delete a snapshot from a VM (consolidates changes into the parent)."""
            await client.delete_snapshot(vm_id, snapshot_id)
            return "ok"

        @mcp.tool()
        async def delete_vm(vm_id: int, force: bool = False, dry_run: bool = False) -> str:
            """Delete a VM from the hypervisor and from Forgemill. Irreversible.
            force=True only removes the Forgemill record without touching the hypervisor.
            Pass dry_run=True to preview what this call would do (hypervisor delete vs.
            untrack-only, plus dependent snapshot/execution counts) without deleting
            anything — recommended before a force=False call on a VM you're unsure about."""
            result = await client.delete_vm(vm_id, force=force, dry_run=dry_run)
            if dry_run:
                return _dump(result)
            return "ok"

        @mcp.tool()
        async def execute_action(
            vm_id: int,
            action_id: int | None = None,
            script: str | None = None,
            parameter_values: dict[str, str] | None = None,
            timeout_seconds: int | None = None,
        ) -> str:
            """Run a saved action (by action_id) or an ad-hoc bash script on a VM via
            SSH. Exactly one of action_id or script must be provided."""
            if (action_id is None) == (script is None):
                return "error: provide exactly one of action_id or script"
            return _dump(
                await client.execute_action(
                    vm_id,
                    action_id=action_id,
                    script=script,
                    parameter_values=parameter_values,
                    timeout_seconds=timeout_seconds,
                )
            )

        @mcp.tool()
        async def cancel_execution(execution_id: int) -> str:
            """Cancel a currently-running action execution."""
            return _dump(await client.cancel_execution(execution_id))

        @mcp.tool()
        async def deploy_from_blueprint(blueprint_id: int, vm_name: str) -> str:
            """Deploy a VM from a saved blueprint."""
            return _dump(
                await client.deploy_blueprint(blueprint_id, vm_name=vm_name)
            )

        def _build_deploy_body(
            template_id: int,
            target_id: int,
            vm_name: str,
            cpu: int,
            memory_mb: int,
            disk_gb: int | None,
            datacenter: str,
            cluster: str,
            host: str,
            datastore: str,
            folder: str,
            network: str,
            ip_address: str,
            netmask: str,
            gateway: str,
            dns: list[str] | None,
            hostname: str,
            domain_name: str,
            ssh_public_key: str,
            action_ids: list[int] | None,
        ) -> dict[str, Any]:
            body: dict[str, Any] = {
                "template_id": template_id,
                "target_id": target_id,
                "vm_name": vm_name,
                "cpu": cpu,
                "memory_mb": memory_mb,
            }
            if disk_gb is not None:
                body["disk_gb"] = disk_gb
            if datacenter:
                body["datacenter"] = datacenter
            if cluster:
                body["cluster"] = cluster
            if host:
                body["host"] = host
            if datastore:
                body["datastore"] = datastore
            if folder:
                body["folder"] = folder
            if network:
                body["network"] = network
            if ip_address:
                body["ip_address"] = ip_address
            if netmask:
                body["netmask"] = netmask
            if gateway:
                body["gateway"] = gateway
            if dns:
                body["dns"] = dns
            if hostname:
                body["hostname"] = hostname
            if domain_name:
                body["domain_name"] = domain_name
            if ssh_public_key:
                body["ssh_public_key"] = ssh_public_key
            if action_ids:
                body["action_ids"] = action_ids
            return body

        @mcp.tool()
        async def deploy_vm(
            template_id: int,
            target_id: int,
            vm_name: str,
            cpu: int,
            memory_mb: int,
            disk_gb: int | None = None,
            datacenter: str = "",
            cluster: str = "",
            host: str = "",
            datastore: str = "",
            folder: str = "",
            network: str = "",
            ip_address: str = "",
            netmask: str = "",
            gateway: str = "",
            dns: list[str] | None = None,
            hostname: str = "",
            domain_name: str = "",
            ssh_public_key: str = "",
            action_ids: list[int] | None = None,
        ) -> str:
            """Deploy a VM directly from a template. Most fields are optional and use
            target defaults. Returns the deployment record including its ID — poll
            with get_deployment to track progress. Consider calling preview_deploy
            first with the same arguments to catch name collisions or a typo'd
            network/datastore/folder/cluster/datacenter before committing."""
            body = _build_deploy_body(
                template_id, target_id, vm_name, cpu, memory_mb, disk_gb,
                datacenter, cluster, host, datastore, folder, network,
                ip_address, netmask, gateway, dns, hostname, domain_name,
                ssh_public_key, action_ids,
            )
            return _dump(await client.deploy_vm(body))

        @mcp.tool()
        async def preview_deploy(
            template_id: int,
            target_id: int,
            vm_name: str,
            cpu: int,
            memory_mb: int,
            disk_gb: int | None = None,
            datacenter: str = "",
            cluster: str = "",
            host: str = "",
            datastore: str = "",
            folder: str = "",
            network: str = "",
            ip_address: str = "",
            netmask: str = "",
            gateway: str = "",
            dns: list[str] | None = None,
            hostname: str = "",
            domain_name: str = "",
            ssh_public_key: str = "",
            action_ids: list[int] | None = None,
        ) -> str:
            """Check whether a deploy_vm call with these exact arguments would be
            accepted, WITHOUT creating anything. Catches an invalid VM name, a VM
            name already in use on the target, and a network/datastore/folder/
            cluster/datacenter name that doesn't exist there. Does not check
            datastore free space or other capacity. Returns {valid, blockers,
            warnings} — a target that can't be reached to verify its resources
            shows up as a warning, not a blocker."""
            body = _build_deploy_body(
                template_id, target_id, vm_name, cpu, memory_mb, disk_gb,
                datacenter, cluster, host, datastore, folder, network,
                ip_address, netmask, gateway, dns, hostname, domain_name,
                ssh_public_key, action_ids,
            )
            return _dump(await client.preview_deploy(body))

        @mcp.tool()
        async def get_deployment(deployment_id: int) -> str:
            """Get the current status and logs of a deployment by ID."""
            return _dump(await client.get_deployment(deployment_id))

        @mcp.tool()
        async def get_deployment_manifest(deployment_id: int) -> str:
            """Get a single receipt for a deployment: what it did, where, who
            triggered it, the exact inputs used, the outcome, a reference to
            where its credentials live (never the credential value itself),
            and concrete undo options (delete/untrack/preview-delete) if a VM
            was created. Use this instead of stitching together get_deployment
            + get_vm_credentials + audit logs by hand."""
            return _dump(await client.get_deployment_manifest(deployment_id))

        @mcp.tool()
        async def get_deployment_timeline(deployment_id: int) -> str:
            """Get a deployment's provisioning logs and audit-trail entries
            merged into one chronological list, oldest first. Use this instead
            of fetching logs and audit events separately and interleaving them
            yourself."""
            return _dump(await client.get_deployment_timeline(deployment_id))

        # --- Action CRUD ---

        @mcp.tool()
        async def create_action(
            name: str,
            script: str,
            description: str = "",
            category: str = "custom",
            platform: str = "linux",
            script_type: str = "bash",
            parameters: list[dict[str, Any]] | None = None,
            tags: list[str] | None = None,
        ) -> str:
            """Create and save a reusable Forgemill custom action.

            category must be one of: packages, scripts, security, monitoring, custom.
            platform is usually linux or windows. parameters is optional and follows
            Forgemill's action parameter schema. tags are free-form searchable
            keywords (e.g. "docker", "database") — Forgemill trims/lowercases/dedupes
            them, max 10 tags of 30 chars each."""
            body: dict[str, Any] = {
                "name": name,
                "description": description,
                "category": category,
                "platform": platform,
                "script_type": script_type,
                "script": script,
                "parameters": parameters or [],
                "tags": tags or [],
            }
            return _dump(await client.create_action(body))

        @mcp.tool()
        async def update_action(
            action_id: int,
            name: str,
            script: str,
            description: str = "",
            category: str = "custom",
            platform: str = "linux",
            script_type: str = "bash",
            parameters: list[dict[str, Any]] | None = None,
            tags: list[str] | None = None,
        ) -> str:
            """Update a reusable Forgemill custom action by ID. Built-in actions
            may be protected by Forgemill. This is a full PUT-style replacement —
            omitting tags clears them, it does not leave existing tags untouched."""
            body: dict[str, Any] = {
                "name": name,
                "description": description,
                "category": category,
                "platform": platform,
                "script_type": script_type,
                "script": script,
                "parameters": parameters or [],
                "tags": tags or [],
            }
            return _dump(await client.update_action(action_id, body))

        @mcp.tool()
        async def delete_action(action_id: int) -> str:
            """Delete a saved Forgemill action by ID. Do not delete built-in/shared actions unless explicitly requested."""
            result = await client.delete_action(action_id)
            return _dump(result or {"status": "deleted"})

        @mcp.tool()
        async def list_action_versions(action_id: int) -> str:
            """List every version of a saved action, newest first — the current
            live content plus every version it superseded. Each edit to an
            action creates a new version rather than overwriting history."""
            return _dump(await client.list_action_versions(action_id))

        @mcp.tool()
        async def get_action_version(action_id: int, version: int) -> str:
            """Get one specific version's content for a saved action (works for
            both the current version and any superseded one)."""
            return _dump(await client.get_action_version(action_id, version))

        @mcp.tool()
        async def rollback_action(action_id: int, version: int) -> str:
            """Restore a saved action's content to an earlier version. This does
            not rewrite history — the restored content becomes a brand new
            version number, like a revert rather than a reset, so nothing already
            recorded is lost. Refuses built-in actions and refuses rolling back
            to the version that's already current."""
            return _dump(await client.rollback_action(action_id, version))

    return mcp


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        settings = Settings.from_env()
    except RuntimeError as e:
        logger.error("%s", e)
        raise SystemExit(2) from None

    logger.info(
        "starting forgemill-mcp",
        extra={
            "forgemill_url": settings.forgemill_url,
            "allow_mutations": settings.allow_mutations,
            "port": settings.mcp_port,
        },
    )
    logger.info("forgemill_url=%s", settings.forgemill_url)
    logger.info("allow_mutations=%s", settings.allow_mutations)
    logger.info("listening on %s:%d", settings.mcp_host, settings.mcp_port)

    client = ForgemillClient(
        base_url=settings.forgemill_url,
        api_key=settings.forgemill_api_key,
        verify=settings.verify_tls,
        timeout=settings.request_timeout_seconds,
    )
    mcp = build_server(settings, client)

    # Streamable HTTP transport — recommended for containerised servers.
    # See https://gofastmcp.com/deployment/running-server
    mcp.run(
        transport="streamable-http",
        host=settings.mcp_host,
        port=settings.mcp_port,
    )


if __name__ == "__main__":
    main()
