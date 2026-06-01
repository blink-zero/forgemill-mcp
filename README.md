# forgemill-mcp

**Model Context Protocol server for [Forgemill](https://github.com/blink-zero/forgemill).**

Lets Claude (Desktop, Code, or the API) talk to your Forgemill instance directly — query targets, templates, and VMs in natural language, and (optionally) deploy, power-cycle, snapshot, or run actions against VMs without leaving the chat.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org)

> Read-only by default. Mutating tools are gated behind a single env flag so the server is safe to plug in and explore with.

---

## Quick start

```bash
docker run -d \
  --name forgemill-mcp \
  -p 3030:3030 \
  -e FORGEMILL_URL="https://forgemill.example.com" \
  -e FORGEMILL_API_KEY="fm_..." \
  ghcr.io/blink-zero/forgemill-mcp:latest
```

The server will listen on `http://localhost:3030/mcp` using the **Streamable HTTP** transport.

Then wire it into your MCP client of choice — see [Client setup](#client-setup) below.

### Generate the API key

In Forgemill: **Settings → API Keys → Create**. Copy the `fm_...` token immediately (it's only shown once).

---

## Configuration

All configuration is via environment variables.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FORGEMILL_URL` | ✅ | — | Base URL of your Forgemill server, e.g. `https://forgemill.example.com` |
| `FORGEMILL_API_KEY` | ✅ | — | A Forgemill API key (`fm_...`) |
| `FORGEMILL_VERIFY_TLS` | | `true` | Set to `false` to skip TLS verification (self-signed certs) |
| `FORGEMILL_MCP_ALLOW_MUTATIONS` | | `false` | When `true`, the write tools (power, deploy, execute, snapshot, delete) are registered |
| `FORGEMILL_MCP_PORT` | | `3030` | Port to listen on |
| `FORGEMILL_MCP_HOST` | | `0.0.0.0` | Host to bind |
| `FORGEMILL_MCP_AUTH_TOKEN` | | — | Optional bearer token clients must send to reach the MCP server (defence-in-depth when exposing beyond localhost) |
| `FORGEMILL_REQUEST_TIMEOUT` | | `30` | Per-request timeout (seconds) to the Forgemill API |

---

## Tools

### Always available (read-only)

- `server_version` — Forgemill version and commit
- `dashboard_summary` — counts and recent activity
- `list_targets` / `get_target` / `get_target_resources` — configured hypervisors + their datastore/network/folder inventory
- `list_templates` / `get_template` — synced templates
- `list_vms` — managed VMs, with optional filters: `power_state`, `target_name`, `os_match`
- `get_vm` — full VM record
- `list_vm_snapshots` — snapshots for a VM
- `list_vm_disks` — disks attached to a VM
- `list_vm_executions` — action history for a VM
- `get_vm_console_url` — VMRC / noVNC URL for a VM *(admin-only on the Forgemill side)*
- `list_actions` — available post-deploy actions
- `get_execution` — execution details and output
- `list_blueprints` — saved deployment blueprints
- `list_history` — paginated deployment history with status / target / search filters
- `list_notifications` — in-app notifications for the API-key owner

### Gated (set `FORGEMILL_MCP_ALLOW_MUTATIONS=true`)

VM lifecycle:
- `power_vm(vm_id, action)` — `start` / `stop` / `restart` / `suspend`
- `sync_vm(vm_id)` / `sync_all_vms()` — force a hypervisor refresh
- `resize_vm(vm_id, cpu, memory_mb)`
- `expand_vm_disk(vm_id, disk_key, new_size_gb)`
- `create_snapshot(vm_id, name, description?, memory?)`
- `revert_snapshot(vm_id, snapshot_id)`
- `delete_snapshot(vm_id, snapshot_id)`
- `delete_vm(vm_id, force?)`
- `get_vm_credentials(vm_id)` — reveals stored deploy-time SSH credentials (sensitive, audit-logged)

Actions:
- `execute_action(vm_id, action_id? | script?, parameter_values?, timeout_seconds?)`
- `cancel_execution(execution_id)`

Deployment:
- `deploy_vm(...)` — full template-based deploy with cloud-init fields
- `deploy_from_blueprint(blueprint_id, vm_name)`
- `get_deployment(deployment_id)`

Targets:
- `test_target(target_id)` — runs a connection test (returns `success: bool`)
- `sync_target_templates(target_id)` — pulls the latest templates from a target

Each mutating call still goes through the regular Forgemill RBAC checks — the API key inherits its user's role.

**Heads up on roles** — most mutating endpoints in Forgemill require **admin** (power, snapshot, delete, resize, disk expand, target test/sync, VM credentials). `execute_action`, `deploy_vm`, and `deploy_from_blueprint` are **user+**. If your API key is for a viewer or user, the corresponding tools will return a 403 from Forgemill. Plan accordingly when issuing the key.

---

## Client setup

### Claude Code

```bash
claude mcp add forgemill --transport http --url http://localhost:3030/mcp
```

Or add an entry to your `~/.claude.json` / project `.claude/settings.json`:

```json
{
  "mcpServers": {
    "forgemill": {
      "transport": "http",
      "url": "http://localhost:3030/mcp"
    }
  }
}
```

If you set `FORGEMILL_MCP_AUTH_TOKEN`, add a `headers` field:

```json
"headers": { "Authorization": "Bearer YOUR_MCP_TOKEN" }
```

### Claude Desktop

In `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or the equivalent on Windows:

```json
{
  "mcpServers": {
    "forgemill": {
      "transport": {
        "type": "http",
        "url": "http://localhost:3030/mcp"
      }
    }
  }
}
```

Restart Claude Desktop. You should see a hammer icon and the tools listed.

### Anthropic API (Managed Agents / Skills)

Use the [MCP connector](https://docs.anthropic.com/en/docs/agents/mcp-connector) and point it at `http://your-mcp-host:3030/mcp`.

---

## Example prompts

Once the server is connected:

> "List all powered-off VMs on the prod-vcenter target."

> "Show me the latest deployment that failed and tell me why."

> "What templates do we have available that are Ubuntu?"

> "Build me a summary of the last 24 hours of activity."

With mutations enabled:

> "Snapshot every running VM on prod-vcenter, call it 'pre-upgrade-2026-06-01'."

> "Deploy two web-server VMs (web-01 and web-02) from the ubuntu-2404 template on prod-vcenter with 4 vCPU and 8GB RAM each."

---

## Security notes

- **Run read-only by default.** The mutating flag is a deliberate opt-in.
- **Bearer-token your MCP endpoint** (`FORGEMILL_MCP_AUTH_TOKEN`) any time you expose it beyond `localhost`.
- **Reverse-proxy with TLS** if accessed across a network.
- **Forgemill API key permissions are inherited** — the MCP server can only do what the underlying user can do. Create a dedicated user with the minimum role you actually need.
- The container runs as a non-root user (UID 1001) with `no-new-privileges`, all caps dropped, and a read-only root filesystem in the example compose.

---

## Develop locally

```bash
git clone https://github.com/blink-zero/forgemill-mcp.git
cd forgemill-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

export FORGEMILL_URL="https://forgemill.example.com"
export FORGEMILL_API_KEY="fm_..."
forgemill-mcp
```

Lint and tests:

```bash
ruff check .
mypy src
pytest
```

---

## Versioning

Released images are published to `ghcr.io/blink-zero/forgemill-mcp` on every tag matching `v*.*.*`. The mainline tag (`:latest`) tracks `main`.

---

## License

[MIT](./LICENSE) — 2026 Forgemill Contributors
