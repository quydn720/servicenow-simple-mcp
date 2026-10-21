# ServiceNow MCP Server

A Model Context Protocol (MCP) server that lets Claude and other MCP clients
work with ServiceNow: search and read incidents, knowledge articles, change
requests and agile work, and (in the local mode) create records after the user
approves each change.

It runs in one of two ways:

| | **stdio** (local) | **remote** (HTTP) |
| --- | --- | --- |
| Runs | On the user's machine, launched by the MCP client | As a service, behind HTTPS |
| Used from | Claude Desktop and other local MCP clients | Claude as a custom connector |
| ServiceNow identity | One configured account (Basic or OAuth) | Each user signs in; their own roles and ACLs apply |
| Tools | Reads and writes; every write needs an approved preview | Reads only |
| Start with | [Start the server: stdio](#start-the-server-stdio) | [Start the server: remote](#start-the-server-remote) |

## Install

Requires Python 3.11 or newer. [uv](https://docs.astral.sh/uv/) installs the
exact locked dependencies; pip uses the declared version ranges.

```bash
git clone https://github.com/quydn720/servicenow-simple-mcp.git servicenow-mcp
cd servicenow-mcp
uv sync --locked --no-dev                  # stdio
uv sync --locked --no-dev --extra remote   # remote (adds its dependencies)
```

Without uv: `python3 -m venv .venv && .venv/bin/pip install -e ".[remote]"`
(drop `[remote]` for stdio only). Commands below assume the virtual environment
is active (`source .venv/bin/activate`) or are prefixed with `uv run`.

## Start the server: stdio

The stdio server runs on your machine and talks to ServiceNow as one
configured account. Use a dedicated integration account with only the roles
the tools need.

### 1. Configure

Run commands from the project folder, which holds `.env`:

```bash
cp -n .env.example .env   # only for a new installation; keeps an existing .env
```

`.env` holds the instance and credentials and is never committed:

```env
SERVICENOW_INSTANCE=https://yourinstance.service-now.com
SERVICENOW_AUTH_TYPE=oauth
SERVICENOW_OAUTH_CLIENT_ID=your-client-id
SERVICENOW_OAUTH_CLIENT_SECRET=your-client-secret
```

For OAuth, create the client in ServiceNow under **System OAuth → Application
Registry → New → Create an OAuth API endpoint for external clients**, with the
redirect URL exactly `http://localhost:8765/callback`. Basic authentication and
other options are in [authentication](docs/authentication.md).

### 2. Sign in (OAuth)

```bash
servicenow-oauth-setup
```

This opens ServiceNow in your browser, receives the authorization code on a
one-time listener bound to `127.0.0.1:8765`, and saves the refresh token to
`.env`. Restart the MCP client afterwards so it loads the new token.

### 3. Run

```bash
servicenow-mcp            # or: python -m servicenow_mcp.servers.stdio
```

MCP clients normally start it themselves, as below.

### 4. Connect Claude Desktop

Open **Settings → Developer → Edit Config** (the file is
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS and
`%APPDATA%\Claude\claude_desktop_config.json` on Windows), and add an entry to
`mcpServers`, keeping any others:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "/path/to/servicenow-mcp/.venv/bin/python",
      "args": ["-m", "servicenow_mcp.servers.stdio"],
      "env": {
        "MCP_ENV_FILE": "/path/to/servicenow-mcp/.env"
      }
    }
  }
}
```

Replace `/path/to/servicenow-mcp` with the project folder's absolute path. Paths
with spaces need no extra quoting inside JSON. On Windows, use
`.venv\\Scripts\\python.exe` and double the backslashes (for example
`C:\\Projects\\servicenow-mcp\\.env`). `MCP_ENV_FILE` lets the server find
`.env` when Claude Desktop starts it from another folder.

Fully quit and reopen Claude Desktop, then check that `servicenow` connects
under **Settings → Developer**. If it does not:

- `No module named servicenow_mcp`: install the package with the same Python
  as `command`.
- Missing ServiceNow configuration when a tool runs: check `MCP_ENV_FILE` and
  the values in `.env`.
- Start-up errors: see `~/Library/Logs/Claude/mcp-server-servicenow.log` on
  macOS, or `%APPDATA%\Claude\logs` on Windows.

More detail: the [MCP guide to connecting local servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers).

### Optional: status dashboard

```bash
uv sync --locked --no-dev --extra dashboard
servicenow-mcp-dashboard
```

Open http://127.0.0.1:5050 to start and stop the stdio server. It listens on
localhost only.

## Start the server: remote

The remote server is a read-only Streamable HTTP server for the Claude
connector. Each user signs in through ServiceNow (and its SSO), so ServiceNow
applies their own permissions. It never holds a shared account.

### 1. Set up ServiceNow (an administrator, once per environment)

- An OAuth client in the Application Registry (confidential), with the
  redirect URL `https://<public host>/auth/callback`.
- The identity API from [`servicenow/identity_api.js`](servicenow/identity_api.js),
  a Scripted REST API the server uses to check each user's token.
- For test and production, an auth scope that limits tokens to the APIs the
  server needs.

Step-by-step instructions are in the [remote server guide](docs/remote-server.md)
and [ServiceNow access management](docs/servicenow-access.md).

### 2. Configure

```bash
cp -n .env.remote.example .env.remote
```

Set at least `MCP_ENVIRONMENT`, `MCP_SERVICENOW_INSTANCE`, `MCP_PUBLIC_URL`,
`MCP_SERVICENOW_CLIENT_ID`, `MCP_IDENTITY_PATH` and
`MCP_ALLOWED_REDIRECT_URIS`. Give secrets as files rather than values, for
example `MCP_SERVICENOW_CLIENT_SECRET_FILE`, `MCP_SIGNING_KEY_FILE` and
`MCP_ENCRYPTION_KEY_FILE`; test and production refuse to start with a secret
written in `.env.remote`. Every setting is described in `.env.remote.example`
and [deployment](docs/deployment.md).

### 3. Validate

```bash
servicenow-mcp-check-remote
```

It checks the settings for the environment, that ServiceNow recognizes the
OAuth client, and that the identity API refuses anonymous calls, without
signing anyone in.

### 4. Run

```bash
servicenow-mcp-remote     # or: python -m servicenow_mcp.servers.remote
```

It listens on `127.0.0.1:8000`. Put HTTPS in front of it with a reverse proxy
([`deploy/Caddyfile`](deploy/Caddyfile)) or, for development, a tunnel. It must
be reachable from Anthropic's cloud, not only from your network. To run it as a
container, see [deployment](docs/deployment.md).

### 5. Connect Claude

In Claude, open **Customize → Connectors → Add custom connector** (for an
organization, an administrator adds it under **Organization settings →
Connectors**) and enter `https://<public host>/mcp`. Each user then signs in to
ServiceNow from Claude.

Operating it: [runbooks](docs/runbooks.md), [performance](docs/performance.md).

## Tools

| Feature group | Tools |
| --- | --- |
| `common` | `list_records`, `get_record` |
| `service_desk` | `list_incidents`, `get_incident`, `list_knowledge_articles`, `get_change_status`, the `get_incident` prompt; stdio only: `create_incident`, `update_incident_journal`, `create_task` |
| `product_owner` (stdio) | Agile story and epic create/get/list/update; product get/list |
| `developer` | Reserved; currently empty |

The stdio server enables groups with `MCP_ENABLED_FEATURES` (default
`common,service_desk,product_owner`); groups control what clients see, not
ServiceNow permissions. The remote server always offers the six read tools.

- **Writes need approval.** Create and update tools only prepare a preview; the
  change happens after the user approves it and the client calls
  `confirm_pending_write`. See [write review](docs/write-review.md).
- **No raw queries.** Searches take structured arguments; a caller-supplied
  ServiceNow query is rejected with `RAW_QUERY_PROHIBITED`.
- **Typed contracts.** Every tool publishes input and output schemas and
  validates both; errors are structured, with MCP `isError: true`. See
  [tool contracts](docs/tool-contracts.md) and [error handling](docs/error-handling.md).
- **Versions.** Each tool's contract version is in `tools/list` as
  `_meta.fastmcp.version`; tool names never change. See the
  [service-desk specifications](docs/service-desk-tools.md),
  [common tools](docs/common-tools.md) and [agile planning](docs/agile-planning.md).
- **Display values.** References are returned as display names (for example
  `"assignment_group": "Service Desk"`); other fields keep raw values, except
  that `list_incidents` and `get_incident` return `state` and `priority` labels
  and omit `sys_id`.

## Development

```bash
uv sync --locked --all-extras --group dev
uv run --locked pytest -q
uv run --locked ruff check .
```

Tests use mocked ServiceNow responses and never change a live instance. CI runs
the same checks, a dependency vulnerability scan, a container build and an
alert-rule check; see [dependencies](docs/dependencies.md).

To add or change a tool, follow [architecture](docs/architecture.md) and the
[MCP tool design standard](docs/mcp-tool-design-standard.md), including its
specification template and review checklist.

```text
src/servicenow_mcp/
├── auth/           # ServiceNow authentication, and the remote OAuth broker
├── servers/        # stdio and remote entry points, rate limiting
├── config/         # Settings, secrets, environment files
├── client.py       # ServiceNow Table API client
├── tools/          # Tools by feature group, contracts, write review
├── observability/  # Logs and metrics (remote)
├── dashboard/      # Optional local dashboard
└── cli/            # Setup and validation commands
```

| Command | What it does |
| --- | --- |
| `servicenow-mcp` | Start the stdio server |
| `servicenow-mcp-remote` | Start the remote server |
| `servicenow-mcp-dashboard` | Start the local dashboard |
| `servicenow-oauth-setup` | Obtain the stdio server's OAuth refresh token |
| `servicenow-mcp-check-remote` | Validate a remote environment's ServiceNow access |
| `servicenow-check-incident-states` | Check incident state labels against an instance |

Each command is also available as `python -m servicenow_mcp.<module>`.

## Ownership and releases

Do Ngoc Quy owns the server and every tool. Releases are tagged `vX.Y.Z` on
`main` and recorded in [CHANGELOG.md](CHANGELOG.md), which also describes the
release process.
