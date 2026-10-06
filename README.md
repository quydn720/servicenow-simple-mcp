# Easy MCP Server

## Remote end-user authorization POC

A separate read-only Streamable HTTP server supports per-user ServiceNow OAuth
through corporate SSO, with approved MCP client callbacks and encrypted token
storage. See [the design and setup guide](docs/remote-auth-poc.md). Start it with
`python -m servicenow_mcp.servers.remote` after configuring `.env.remote`; the local stdio
server described below remains available.

This project is a starter Model Context Protocol (MCP) server for a ServiceNow Personal Developer Instance (PDI). It exposes a small set of safe tools for reading and creating records while keeping the default scope narrow and secure.

## What this starter includes

- Read records from a ServiceNow table
- List records with a limit (caller-supplied raw queries are blocked)
- Create a task record
- Basic or OAuth 2.0 authentication via environment variables
- Configurable tools grouped by feature
- Clear separation between MCP tool definitions and the ServiceNow API client

## Recommended security posture

- Use a dedicated ServiceNow integration user
- Grant only minimum required roles
- Keep credentials in environment variables
- Only allow safe tables and read/write actions
- Do not expose admin-only endpoints in the first version

## Quick start

Requires Python 3.11 or newer. Run setup and server commands from the directory
containing your `.env`. For a client launched elsewhere, set `MCP_ENV_FILE` to
its absolute path; remote startup uses `MCP_REMOTE_ENV_FILE` for `.env.remote`.
Environment variables override values loaded from these files. Importing a
server module does not load credentials or create a server.


1. Create a virtual environment

   ```bash
   cd "/Users/quydo/My MCP"
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies

   ```bash
   pip install -e .
   # Optional local dashboard:
   pip install -e ".[dashboard]"
   ```

3. Configure credentials

   Copy the example file and update the values:

   ```bash
   # Only for a new installation; preserve an existing .env.
   cp -n .env.example .env
   ```

   Example OAuth values:

   ```env
   SERVICENOW_INSTANCE=yourinstance.service-now.com
   SERVICENOW_OAUTH_CLIENT_ID=your-oauth-client-id
   SERVICENOW_OAUTH_CLIENT_SECRET=your-oauth-client-secret
   SERVICENOW_OAUTH_REFRESH_TOKEN=your-oauth-refresh-token
   ```

   In ServiceNow, open **System OAuth → Application Registry → New →
   Create an OAuth API endpoint for external clients**. Set the redirect URL
   below, then save the generated client ID and client secret in `.env`.
   The setup command obtains the refresh token through an authorization-code
   flow. Store the real values only in `.env`.

   The redirect URL must be exactly:

   ```text
   http://localhost:8765/callback
   ```

   Run the automatic OAuth setup flow:

   ```bash
   python -m servicenow_mcp.cli.oauth_setup
   ```

   This opens ServiceNow in your browser, starts a one-time local callback
   listener, exchanges the authorization code, and saves the refresh token to
   `.env`. No copy/paste of the code is required. The listener binds only to
   `127.0.0.1` and stops after the callback. Use `servicenow_mcp.cli.oauth_setup` for this
   flow; do not run the older `servicenow_mcp.cli.legacy_oauth_callback` listener at the same time
   because it uses the same port. The legacy listener is retained only for manual troubleshooting. Restart your MCP client/server after setup
   so it loads the updated `.env`.

4. Start the MCP server

   ```bash
   python -m servicenow_mcp.servers.stdio
   ```

## Claude Desktop setup

Install the package into this project's virtual environment before configuring
Claude Desktop. From the project root, use `uv sync --locked --no-dev`, or:

```bash
"/Users/quydo/My MCP/.venv/bin/python" -m pip install -e "/Users/quydo/My MCP"
```

In Claude Desktop, open **Settings → Developer → Edit Config**. The configuration
file is `~/Library/Application Support/Claude/claude_desktop_config.json` on
macOS, or `%APPDATA%\Claude\claude_desktop_config.json` on Windows. Add the
following entry to `mcpServers`, preserving any other servers and settings:

```json
{
  "mcpServers": {
    "servicenow-pdi": {
      "command": "/Users/quydo/My MCP/.venv/bin/python",
      "args": ["-m", "servicenow_mcp.servers.stdio"],
      "env": {
        "MCP_ENV_FILE": "/Users/quydo/My MCP/.env"
      }
    }
  }
}
```

Replace the absolute paths with your project location. Paths containing spaces
are ordinary JSON strings; do not add shell quotes inside the values. On
Windows, use `.venv\\Scripts\\python.exe` and escape backslashes in JSON paths
(for example, `C:\\Projects\\My MCP\\.env`). Keep credentials in the `.env` file
described in the quick start. The explicit `MCP_ENV_FILE` path lets the server
find that file when Claude Desktop launches from a different working directory.

If upgrading from the old layout, replace the argument pointing to
`app/server.py` with the two module arguments above. The `src/` layout requires
installing the package; pointing directly at `src/servicenow_mcp/servers/stdio.py`
does not replace that installation.

Save the configuration, fully quit Claude Desktop, and reopen it. Check that
`servicenow-pdi` connects in Developer settings. If it fails:

- `No module named servicenow_mcp`: install the package using the exact Python
  interpreter configured in `command`.
- A missing `app/server.py` error: update the stale launch arguments and restart
  Claude Desktop.
- Missing ServiceNow configuration when invoking a tool: check `MCP_ENV_FILE`
  and the required values in `.env`.
- For startup errors, inspect `~/Library/Logs/Claude/mcp-server-servicenow-pdi.log`
  on macOS, or `%APPDATA%\Claude\logs` on Windows.

See the [official MCP desktop connection guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
for configuration and troubleshooting details. This entry runs the local stdio
server; remote OAuth setup is documented in [the remote guide](docs/remote-auth-poc.md).

## Local status dashboard

Run the dashboard from the project root:

```bash
cd "/Users/quydo/My MCP"
. .venv/bin/activate
python -m servicenow_mcp.dashboard.web
```

Open http://127.0.0.1:5050 in your browser. Use the dashboard to start and
stop the stdio MCP server. The dashboard is bound to localhost only.

## Example tools exposed

- `list_records` — list records in a table
- `get_record` — fetch one record by `sys_id`
- `create_task` — create a task with safe required fields

Returned records use display names for reference fields, such as
`"assignment_group": "Service Desk"` and `"assigned_to": "Jane Doe"`.
This applies to list, get, create, and update responses. The record's own
`sys_id`, choice codes, and timestamps retain their raw values. Queries and
write payloads still use reference sys_ids.

### Raw-query security change

`list_records`, `list_agile_stories`, `list_agile_epics`, and
`list_agile_products` reject every supplied `query` string, including empty
strings, with a `RAW_QUERY_PROHIBITED` tool error before creating a ServiceNow
client. This applies to local tools and the remote `list_records` tool.
The argument is retained for clear rejection of older client calls; omit it or
pass `null` for unfiltered lists. Existing callers that supply queries must
change their calls. Structured filters and owner-approved exception execution
are not implemented, so approval alone cannot enable raw queries. This is a
security restriction; remaining contract migrations are separate work.

### Typed tool contracts

All 15 local tools (and the two shared remote read tools) publish explicit
input/output schemas and validate arguments and results. See
[implemented tool contracts](docs/tool-contracts.md) for field allowlists,
limits, result variants, and compatibility changes. Existing names and response
envelopes are retained, but malformed IDs, undeclared fields, invalid priorities,
oversized text, and limits outside 1–100 are now rejected.

Tool execution failures return a structured standard error with MCP `isError: true`.
See [error handling and recovery](docs/error-handling.md), especially the migration
note for clients that previously received write failures as successful MCP calls.

## Authentication

See [authentication](docs/authentication.md).

## Feature groups

```env
MCP_ENABLED_FEATURES=common,service_desk,product_owner
```

| Group | Registered tools and prompts |
| --- | --- |
| `common` | `list_records`, `get_record` |
| `service_desk` | `create_incident`, `create_task`, `get_incident` prompt |
| `product_owner` | Story and epic create/get/list/update tools; product get/list tools |
| `developer` | Reserved for future catalog use cases; currently empty |

Omitting the setting enables the first three groups and preserves existing
tool names and existing story arguments. Whitespace and duplicate names are accepted. Unknown groups
or an explicitly empty list stop startup. Groups control MCP discovery; they do
not change ServiceNow ACLs. The incident prompt references `get_record`, so enable
`common` alongside `service_desk` when using that prompt.

## Architecture and adding tools

See [architecture and adding tools](docs/architecture.md).

Tool authors and reviewers must follow the [MCP tool design standard](docs/mcp-tool-design-standard.md),
including its contract template and review checklist. The standard documents
target requirements and current compliance gaps; it does not change runtime behavior.

## Agile planning

See [agile planning](docs/agile-planning.md).

## Required review before ServiceNow writes

See [required review before servicenow writes](docs/write-review.md).

## Read-only connection check

Configure either Basic or OAuth using the [authentication guide](docs/authentication.md),
then run the check from the project root using the virtual environment. This requests at most one incident ID and
prints only a success message; it does not create or update records.

```bash
python - <<'PYTHON'
from servicenow_mcp.config.environment import load_environment
from servicenow_mcp.config.local import Settings
from servicenow_mcp.client import ServiceNowClient

load_environment()
client = ServiceNowClient(Settings.from_env())
client.list_records('incident', fields=['sys_id'], limit=1)
print('Authentication and Table API read succeeded.')
PYTHON
```

Install the complete development environment with
`uv sync --locked --all-extras --group dev`, then run `uv run --locked pytest -q`
and `uv run --locked ruff check .`. Authentication and tool tests use
mocked HTTP/clients and do not create live ServiceNow records. The dashboard
continues to control its local subprocess; MCP clients launch their own stdio
server with `python -m servicenow_mcp.servers.stdio`.

## Package layout and commands

```text
src/servicenow_mcp/
├── auth/       # ServiceNow authentication providers
├── servers/    # Local stdio and remote HTTP server factories and entry points
├── config/     # Local/remote settings and explicit environment-file loading
├── client.py   # ServiceNow HTTP and Table API client
├── tools/      # Feature registry, tool groups, and write previews
├── dashboard/  # Optional Flask dashboard and packaged HTML templates
└── cli/        # OAuth setup and legacy manual callback listener
```

The repository also contains `tests/`, `docs/`, `deploy/`, and `servicenow/`
(the instance-side identity endpoint). Project dependencies and tooling live
in `pyproject.toml`; `uv.lock` records exact resolved dependencies. Core runtime
installs exclude Flask and development tools; remote and dashboard extras are
optional. `uv sync --locked --no-dev` installs the locked core runtime;
add `--extra remote` or `--extra dashboard` as needed. Pip installations use
the declared dependency constraints; use uv for the exact locked environment.

| Installed command | Python module alternative |
| --- | --- |
| `servicenow-mcp` | `python -m servicenow_mcp.servers.stdio` |
| `servicenow-mcp-remote` | `python -m servicenow_mcp.servers.remote` |
| `servicenow-mcp-dashboard` | `python -m servicenow_mcp.dashboard.web` |
| `servicenow-oauth-setup` | `python -m servicenow_mcp.cli.oauth_setup` |

After this refactor, install the package and update MCP client launch commands
that previously pointed to `app/server.py` or `app.*`. For example, use the
absolute path to `.venv/bin/servicenow-mcp` and set `MCP_ENV_FILE` in the client
environment. Tool names, arguments, and ServiceNow environment variables are
unchanged. The remote setup guide is in [docs/remote-auth-poc.md](docs/remote-auth-poc.md).
