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
    async def list_actions() -> str:
        """List available post-deploy actions (built-in and custom)."""
        return _dump(await client.list_actions())

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
        async def sync_all_vms() -> str:
            """Force an immediate refresh of every VM's state from its hypervisor."""
            return _dump(await client.sync_all_vms())

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
        async def delete_vm(vm_id: int, force: bool = False) -> str:
            """Delete a VM from the hypervisor and from Forgemill. Irreversible.
            force=True only removes the Forgemill record without touching the hypervisor."""
            await client.delete_vm(vm_id, force=force)
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
            with get_deployment to track progress."""
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
            return _dump(await client.deploy_vm(body))

        @mcp.tool()
        async def get_deployment(deployment_id: int) -> str:
            """Get the current status and logs of a deployment by ID."""
            return _dump(await client.get_deployment(deployment_id))

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
