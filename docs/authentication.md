# Authentication

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

Use `python -m servicenow_mcp.cli.oauth_setup` to obtain the refresh token using
the [quick start](../README.md#quick-start).
For an externally managed access token, leave the refresh token blank and set
`SERVICENOW_OAUTH_ACCESS_TOKEN`; client ID and secret are not required in this
mode. If both tokens exist, the refresh token takes precedence. Only credentials
for the selected authentication mode are validated. Tools create a fresh client
per invocation; refresh mode exchanges the refresh token on each invocation.
There is no token cache or automatic retry of failed writes.
