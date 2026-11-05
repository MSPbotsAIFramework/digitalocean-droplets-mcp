# digitalocean-droplets-mcp

MCP server exposing DigitalOcean Droplets (virtual machine) lifecycle management to
MCP-compatible AI agents: list, create, and destroy Droplets; drive their lifecycle
(power on/off, power-cycle, reboot, shutdown, resize, rename, snapshot, restore,
enable/disable backups, enable IPv6); inspect snapshots and backups; and look up the
regions, sizes, and images needed to create a Droplet.

Transport: MCP Streamable HTTP (`POST /mcp`), stateless, no session affinity required.
Stack: Python 3.12, FastMCP, httpx.
License: proprietary (MSPbots internal connector).

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

| Header | Required | Meaning | Where to get it |
|---|---|---|---|
| `X-DigitalOcean-Api-Token` | Yes | DigitalOcean personal access token (Bearer token for the DigitalOcean API v2) | DigitalOcean Control Panel → **Account → API → Tokens** → Generate New Token |

The token is read exclusively from this header on every request; it is never logged,
never persisted, and never falls back to an environment variable.

## Tools

13 tools, all prefixed `digitalocean_`:

| Tool | Description | Semantics |
|---|---|---|
| `digitalocean_list_droplets` | List Droplets on the account (optional `tag_name` filter) | read-only |
| `digitalocean_get_droplet` | Get one Droplet's full record by id | read-only |
| `digitalocean_create_droplet` | Create a new Droplet | — |
| `digitalocean_delete_droplet` | Destroy one Droplet by id | destructive |
| `digitalocean_droplet_action` | Perform one lifecycle action on a Droplet (power_on, power_off, power_cycle, shutdown, reboot, resize, rename, snapshot, restore, enable_backups, disable_backups, enable_ipv6) | destructive |
| `digitalocean_list_droplet_actions` | List the actions performed on a Droplet | read-only |
| `digitalocean_get_action` | Get one action's current status by id | read-only, idempotent |
| `digitalocean_list_snapshots` | List a Droplet's snapshots | read-only |
| `digitalocean_delete_snapshot` | Destroy one snapshot by id | destructive |
| `digitalocean_list_backups` | List a Droplet's automatic backups | read-only |
| `digitalocean_list_regions` | List DigitalOcean regions and their slugs | read-only |
| `digitalocean_list_sizes` | List DigitalOcean Droplet sizes and their slugs | read-only |
| `digitalocean_list_images` | List DigitalOcean images (distribution/application/private) | read-only |

Scope: this connector covers DigitalOcean **Droplets** only. Other DigitalOcean products
(Databases, Spaces, Kubernetes, etc.) are separate connectors.

## Error envelope

Every tool returns a JSON string. On failure:

```json
{"error": {"code": "not_found", "message": "Droplet 123456789 not found", "retryable": false}}
```

`code` is one of `not_configured`, `unauthorized`, `not_found`, `invalid_argument`,
`rate_limited`, `upstream_error`.

## Local development

```bash
uv sync --all-groups
uv run pytest tests/ -v
PYTHONPATH=src uv run python -m digitalocean_droplets_mcp
```

Then, in another terminal:

```bash
curl http://localhost:8080/health
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "X-DigitalOcean-Api-Token: <your real token>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Container

```bash
docker build --platform linux/amd64 -t digitalocean-droplets-mcp:dev .
docker run --rm -p 8080:8080 digitalocean-droplets-mcp:dev
```
