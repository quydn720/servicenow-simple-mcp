# ServiceNow PDI MCP Server

This project is a starter Model Context Protocol (MCP) server for a ServiceNow Personal Developer Instance (PDI). It exposes a small set of safe tools for reading and creating records while keeping the default scope narrow and secure.

## What this starter includes

- Read records from a ServiceNow table
- List records with a query and limit
- Create a task record
- OAuth 2.0 authentication via environment variables
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
   cp .env.example .env
   ```

   Example OAuth values:

   ```env
   SERVICENOW_INSTANCE=yourinstance.service-now.com
   SERVICENOW_OAUTH_CLIENT_ID=your-oauth-client-id
   SERVICENOW_OAUTH_CLIENT_SECRET=your-oauth-client-secret
   SERVICENOW_OAUTH_REFRESH_TOKEN=your-oauth-refresh-token
   ```

   Create an OAuth application in ServiceNow and obtain a refresh token through
   an authorization-code flow. Store the real values only in `.env`.

   The redirect URL must be exactly:

   ```text
   http://localhost:8765/callback
   ```

   Start the local callback listener before opening the ServiceNow authorization
   URL:

   ```bash
   python -m app.oauth_callback
   ```

   After authorization, copy the code printed by the listener into the token
   exchange command. The listener is only for local setup and binds to
   `127.0.0.1`.

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

## OAuth environment variables

```env
SERVICENOW_INSTANCE=yourinstance.service-now.com
SERVICENOW_OAUTH_CLIENT_ID=your-oauth-client-id
SERVICENOW_OAUTH_CLIENT_SECRET=your-oauth-client-secret
SERVICENOW_OAUTH_REFRESH_TOKEN=your-oauth-refresh-token
```

The client exchanges the refresh token at `/oauth_token.do` and sends the
resulting bearer token to the ServiceNow Table API. You can use
`SERVICENOW_OAUTH_ACCESS_TOKEN` instead when managing token refresh elsewhere.

## Notes

This is intentionally conservative. Start with read access and one or two write actions only. Add more tables and operations only after your ACLs and governance rules are confirmed.
