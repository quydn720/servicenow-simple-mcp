# Easy MCP Server

This project is a starter Model Context Protocol (MCP) server for a ServiceNow Personal Developer Instance (PDI). It exposes a small set of safe tools for reading and creating records while keeping the default scope narrow and secure.

## What this starter includes

- Read records from a ServiceNow table
- List records with a query and limit
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

1. Create a virtual environment

   ```bash
   cd "/Users/quydo/My MCP"
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies

   ```bash
   pip install -r requirements.txt
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
   python -m app.oauth_setup
   ```

   This opens ServiceNow in your browser, starts a one-time local callback
   listener, exchanges the authorization code, and saves the refresh token to
   `.env`. No copy/paste of the code is required. The listener binds only to
   `127.0.0.1` and stops after the callback. Use `app.oauth_setup` for this
   flow; do not run the older `app.oauth_callback` listener at the same time
   because it uses the same port. Restart your MCP client/server after setup
   so it loads the updated `.env`.

4. Start the MCP server

   ```bash
   python app/server.py
   ```

## Local status dashboard

Run the dashboard from the project root:

```bash
cd "/Users/quydo/My MCP"
. .venv/bin/activate
python -m app.web
```

Open http://127.0.0.1:5050 in your browser. Use the dashboard to start and
stop the stdio MCP server. The dashboard is bound to localhost only.

## Example tools exposed

- `list_records` — list records in a table
- `get_record` — fetch one record by `sys_id`
- `create_task` — create a task with safe required fields

## Authentication

Authentication applies to outbound ServiceNow API requests. The MCP server uses
local stdio. Set `SERVICENOW_AUTH_TYPE` to `basic` or `oauth`; omitted means
`oauth` for compatibility. Restart the MCP process after configuration changes.
Environment variables already set by the launcher take precedence over `.env`.

Basic authentication:

```env
SERVICENOW_INSTANCE=https://yourinstance.service-now.com
SERVICENOW_AUTH_TYPE=basic
SERVICENOW_USERNAME=integration-user
SERVICENOW_PASSWORD=your-password
```

OAuth with automatic refresh:

```env
SERVICENOW_INSTANCE=https://yourinstance.service-now.com
SERVICENOW_AUTH_TYPE=oauth
SERVICENOW_OAUTH_CLIENT_ID=your-client-id
SERVICENOW_OAUTH_CLIENT_SECRET=your-client-secret
SERVICENOW_OAUTH_REFRESH_TOKEN=your-refresh-token
SERVICENOW_OAUTH_ACCESS_TOKEN=
```

Use `python -m app.oauth_setup` to obtain the refresh token as described above.
For an externally managed access token, leave the refresh token blank and set
`SERVICENOW_OAUTH_ACCESS_TOKEN`; client ID and secret are not required in this
mode. If both tokens exist, the refresh token takes precedence. Only credentials
for the selected authentication mode are validated. Tools create a fresh client
per invocation; refresh mode exchanges the refresh token on each invocation.
There is no token cache or automatic retry of failed writes.

## Feature groups

```env
MCP_ENABLED_FEATURES=common,service_desk,product_owner
```

| Group | Registered tools and prompts |
| --- | --- |
| `common` | `list_records`, `get_record` |
| `service_desk` | `create_incident`, `create_task`, `get_incident` prompt |
| `product_owner` | `create_agile_story` |
| `developer` | Reserved for future catalog use cases; currently empty |

Omitting the setting enables the first three groups and preserves existing
names and schemas. Whitespace and duplicate names are accepted. Unknown groups
or an explicitly empty list stop startup. Groups control MCP discovery; they do
not change ServiceNow ACLs. The incident prompt references `get_record`, so enable
`common` alongside `service_desk` when using that prompt.

## Architecture and adding tools

`server.py` wires configuration, a client factory, and the explicit feature
registry. `create_server(client_factory=...)` supports isolated tests. Discovery
requires neither ServiceNow credentials nor a network connection. Credentials
are validated when a tool requests its client.

The `app/auth` providers implement `authenticate(session)`; the factory selects
Basic or OAuth. `ServiceNowClient` owns HTTP and Table API operations. Feature
modules in `app/tools` own use-case validation, payloads, and MCP results.

To add a use case:

1. Add a module to the appropriate feature package, exporting
   `register(mcp, client_factory)`.
2. Define tools inside that function with `@mcp.tool()`, obtain the client through
   `client_factory()`, and call its API methods. Do not import `app.server` or
   access credentials from tools.
3. Call the module's registration function from its feature package's `register`.
   A new feature also needs an explicit entry in the registry and `KNOWN_FEATURES`.
4. Add mocked tests for discovery, inputs, payloads, and responses. Preserve
   existing MCP names and schemas when extending current use cases.

The developer package is an extension point only. Incident updates, epic creation,
and catalog modifications are not implemented by this architecture update.

## Read-only connection check

Configure either Basic or OAuth above, then run the same check from the project
root using the virtual environment. This requests at most one incident ID and
prints only a success message; it does not create or update records.

```bash
python - <<'PYTHON'
from dotenv import load_dotenv
from app.config import Settings
from app.service_now_client import ServiceNowClient

load_dotenv('.env')
client = ServiceNowClient(Settings.from_env())
client.list_records('incident', fields=['sys_id'], limit=1)
print('Authentication and Table API read succeeded.')
PYTHON
```

Run automated tests with `python -m pytest -q`. Authentication and tool tests use
mocked HTTP/clients and do not create live ServiceNow records. The dashboard
continues to control its local subprocess; MCP clients launch their own stdio
server with `python app/server.py` or `python -m app.server`.
