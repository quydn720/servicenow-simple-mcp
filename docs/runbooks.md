# Runbooks

Owner: Do Ngoc Quy. These runbooks cover the remote MCP server (the Claude
connector). Each alert in [`deploy/monitoring/alerts.yml`](../deploy/monitoring/alerts.yml)
links to the section that handles it. Settings and procedures they refer to
are described in [deployment](deployment.md).

## Where to look first

| Check | How |
| --- | --- |
| Is the process up? | `GET /healthz` returns `{"status":"ok"}`. From inside the network, send `Host: localhost:8000` or use a name in `POC_INTERNAL_HOSTS`. |
| Did it restart? | `mcp_process_start_time_seconds` changes on every start. |
| What failed? | Logs are JSON lines on stdout. Filter by `level` (`ERROR`, `WARNING`); a request's lines share one `request_id`. |
| Is ServiceNow healthy? | `servicenow_responses_total` by `status`, and `servicenow_identity_checks_total` by `result`. |
| Is it overloaded? | `mcp_http_request_duration_seconds` p95 and `mcp_rate_limited_total`. One process saturates near 65 calls/s ([performance](performance.md)). |

Logs never contain tokens, codes, passwords, search values or query strings.
Audit events (`audit` key) identify the ServiceNow user by sys_id.

## Broker outage

Alerts: `ServiceNowMCPDown`, `ServiceNowMCPServerErrors`, `ServiceNowMCPSlowToolCalls`,
`ServiceNowMCPToolErrors`, `ServiceNowMCPRateLimiting`, `ServiceNowMCPRegistrationSpike`.
Users see: Claude reports it cannot reach the connector, or tool calls fail.

1. **Process down or restarting.** Check the container's status and restart
   count, then the last log lines before exit.
   - A `ValueError` naming a setting (for example `POC_ENCRYPTION_KEY`,
     `POC_APPROVED_CLIENTS`, `POC_SIGNING_KEY_FILE`) is a configuration error:
     fix that setting and start again.
   - The token store needs `/data` (`POC_STORAGE_DIR`) writable by UID 10001,
     mode 700, with free space.
2. **Up but returning 5xx.** Find `ERROR` lines and their `request_id`. If they
   follow a deploy, roll back to the previous image.
3. **Slow.** Compare `/mcp` p95 with ServiceNow's response codes: if ServiceNow
   is slow or failing, go to [ServiceNow outage](#servicenow-outage). If traffic is
   above about 65 calls/s, the single process is saturated; do not add replicas
   (the token store is single-process), and record the load for capacity planning.
4. **Rate limiting or registration spike.** Check `mcp_rate_limited_total` by
   `group`. Sustained `sign_in` limiting from one address, or a spike on
   `/register`, suggests abuse: block the source at the proxy. If legitimate
   users are limited, raise the matching `POC_RATE_LIMIT_*_PER_MINUTE` and make
   sure `FORWARDED_ALLOW_IPS` is set, or all browsers share one allowance.
5. **Tool errors.** `mcp_tool_calls_total{outcome="error"}` by `error_code`
   tells you which: `UPSTREAM_ERROR` or `TIMEOUT` point at ServiceNow;
   `INTERNAL_ERROR` is a server bug, so collect the `request_id` and log lines.

Verify: `/healthz` returns 200; discovery
(`/.well-known/oauth-authorization-server`) returns JSON; an unauthenticated
`POST /mcp` returns 401; a tool call from Claude succeeds.

## ServiceNow outage

Alerts: `ServiceNowUnavailable`, `ServiceNowSignInRejections`.
Users see: tool calls fail, or Claude asks them to sign in again.

The broker fails closed: if it cannot check a token with ServiceNow, the
request is refused. No action on the broker restarts ServiceNow.

| Signal | Likely cause | Action |
| --- | --- | --- |
| `status="5xx"` or `"no_response"`; identity checks `servicenow_unavailable` | Instance down, upgrading, or unreachable | Check the instance and the network path. A developer instance hibernates when idle: wake it from the developer portal. Tell users; nothing to change on the broker. |
| `status="429"` | ServiceNow rate limits for the users or integration | Check the instance's REST rate-limit rules; lower `POC_RATE_LIMIT_MCP_PER_MINUTE` if the connector drives it. |
| Identity checks `rejected` rising, `status="401"` | OAuth app inactive or its secret changed; identity API moved; mass token revocation | Check the OAuth app is active and its secret matches `POC_SERVICENOW_CLIENT_SECRET`; check `POC_IDENTITY_PATH` returns the caller with a fresh token. |
| `status="403"` rising | ACL, role or auth-scope change | Check recent ACL changes and, if `POC_SERVICENOW_SCOPE` is set, the REST API auth scopes for the Table API and identity API. |

After recovery, users whose refresh failed during the outage sign in again
once; others continue without action.

## Key rotation

Scheduled rotations follow [deployment: secrets](deployment.md#secrets). Record
each rotation (date, secret, who) in your change log.

1. **Encryption key (no sign-outs).** Set `POC_ENCRYPTION_KEY=<new>,<old>`,
   restart, wait at least `POC_SESSION_LIFETIME_SECONDS` (default 24 h), then
   set `<new>` alone and restart.
2. **Metrics token.** Set `<new>,<old>`, switch the scraper, then remove `<old>`.
3. **ServiceNow client secret.** Regenerate in the Application Registry, update
   the secret, and restart straight away; sign-ins and refreshes fail until
   the restart.
4. **Signing key (signs everyone out).** Announce a time, set the new key,
   restart. Users reconnect the connector.

**Suspected leak.** Rotate the leaked secret immediately, without the waiting
steps. A leaked signing or encryption key also needs the emergency sign-out in
[User offboarding](#user-offboarding), step 4, because existing grants may be
compromised.

Verify after any rotation: the server starts (a bad value stops it with a
`ValueError` naming the setting), and a tool call from Claude succeeds.

## User offboarding

For a leaver, a compromised account, or a mistaken grant. Full detail is in
[deployment: revocation and offboarding](deployment.md#revocation-and-offboarding).

1. **One user.** Deactivate the user in ServiceNow, or revoke their tokens
   under **System OAuth > Manage Tokens**. Every request re-checks the token
   with ServiceNow, so their next tool call fails.
2. **Confirm.** `servicenow_identity_checks_total{result="rejected"}` rises
   if they try again. Their past activity is in the audit events, found by
   their ServiceNow sys_id.
3. **One client application.** Remove its URL from `POC_APPROVED_CLIENTS` and
   restart; its sign-ins end at their next token refresh.
4. **Everyone (emergency).** Stop the server; rotate `POC_SIGNING_KEY`; delete
   the contents of `POC_STORAGE_DIR`; revoke the OAuth app's tokens in
   ServiceNow or deactivate the app; start the server. All users sign in again.

## Drills

Practise each runbook on a staging deployment before relying on it, then
quarterly. A drill is complete when the verify steps pass and the time taken is
recorded.

| Drill | How to run it | Pass when |
| --- | --- | --- |
| Broker outage | Stop the container; restart it. | `ServiceNowMCPDown` fires within 2 minutes; the connector works again after restart. |
| ServiceNow outage | Point `POC_IDENTITY_PATH` at a path that returns 404 (or block the instance at the network). | `ServiceNowSignInRejections` or `ServiceNowUnavailable` fires; tool calls are refused, not answered. |
| Encryption key rotation | Run the encryption-key rotation in staging with a signed-in test user. | The user stays signed in through both restarts. |
| User offboarding | Deactivate a test user in ServiceNow while they are signed in. | Their next tool call fails; another user is unaffected. |

### Drill log

| Date | Drill | Environment | Result | Run by |
| --- | --- | --- | --- | --- |
| – | No drill has been run yet. The first should run in staging before go-live. | | | |
