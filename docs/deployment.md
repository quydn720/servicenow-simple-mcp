# Deploying the remote server

The remote OAuth broker ships as a container image built from the repository's
`Dockerfile`. It is platform-neutral: it reads its configuration from
environment variables, writes JSON logs to stdout, and keeps its
encrypted token store on one mounted volume. Owner: Do Ngoc Quy.

## Image

| Property | Value |
| --- | --- |
| Base | `python:3.13-slim`, dependencies installed from `uv.lock` |
| User | UID/GID 10001, no shell, no home directory |
| Filesystem | Runs with a read-only root filesystem; needs `/tmp` (tmpfs) and `/data` (volume) writable |
| Port | 8000 (`POC_BIND_PORT`), listening on `0.0.0.0` (`POC_BIND_HOST`) inside the container |
| Health | `GET /healthz` returns `{"status":"ok"}` with no sign-in; it checks only that the process serves requests |
| Token store | `/data` (`POC_STORAGE_DIR`), encrypted with `POC_ENCRYPTION_KEY`; mode 700 |

Build and run:

```bash
docker build -t servicenow-mcp-remote .
docker run -d --name servicenow-mcp --read-only --tmpfs /tmp \
  -v servicenow-mcp-data:/data -p 127.0.0.1:8000:8000 \
  --env-file /secure/path/.env.remote \
  servicenow-mcp-remote
```

Every `POC_*` setting in `.env.remote.example` is passed as an environment
variable; the image contains no secrets and `.dockerignore` keeps `.env*` and
`.oauth-poc` out of the build. Use a secret manager rather than an env file in
production.

## Environment

Set `POC_ENVIRONMENT` to `development`, `test` or `production`. Test and
production refuse to start with insecure settings: a secret written in the
`.env.remote` file, no `POC_SERVICENOW_SCOPE`, open dynamic registration, no
revocation path, or (production) a tunnel host as the public URL. The rules
and their reasons are in [ServiceNow access management](servicenow-access.md#environment-and-network-controls).
Run `servicenow-mcp-check-remote` after each deployment to validate access.

## Secrets

Four settings are secrets. Each can be set directly or, preferably, as a file
mounted by your secret manager: set `<NAME>_FILE` to the file's path (for
example `/run/secrets/signing_key`). Files keep secrets out of the process
environment, which `docker inspect` and process listings expose. Setting both
`<NAME>` and `<NAME>_FILE` is an error. Values are read at start-up, so a
rotation takes effect on restart.

| Secret | Setting | Generate with |
| --- | --- | --- |
| ServiceNow OAuth client secret | `POC_SERVICENOW_CLIENT_SECRET` | ServiceNow Application Registry |
| Token-signing key | `POC_SIGNING_KEY` | `python -c 'import secrets; print(secrets.token_urlsafe(48))'` |
| Token-encryption key(s) | `POC_ENCRYPTION_KEY` | `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` |
| Metrics token(s) | `POC_METRICS_TOKEN` | `python -c 'import secrets; print(secrets.token_urlsafe(32))'` |

Example with Docker secrets:

```bash
docker run ... \
  -e POC_SIGNING_KEY_FILE=/run/secrets/signing_key \
  -e POC_ENCRYPTION_KEY_FILE=/run/secrets/encryption_key \
  -e POC_SERVICENOW_CLIENT_SECRET_FILE=/run/secrets/servicenow_client_secret \
  -v /secure/secrets:/run/secrets:ro servicenow-mcp-remote
```

### Rotation

**Encryption key: no sign-outs.** The setting takes a comma-separated list,
newest first. The first key encrypts; every listed key decrypts.

1. Generate a key and set `POC_ENCRYPTION_KEY=<new>,<old>`. Restart.
2. Grants are re-encrypted with the new key as users' tokens refresh. Wait at
   least `POC_SESSION_LIFETIME_SECONDS` (default 24 hours).
3. Set `POC_ENCRYPTION_KEY=<new>`. Restart.

A grant that no listed key can read is treated as absent, so dropping the old
key too early signs those users out rather than causing errors.

**Signing key: signs everyone out.** FastMCP accepts a single signing key, so
every issued Claude token becomes invalid. Schedule it, announce it, set the
new key and restart; users reconnect the connector and sign in again. Rotate it
immediately if it may have leaked.

**ServiceNow client secret.** ServiceNow keeps one secret per OAuth app.
Regenerate it in the Application Registry, update the secret, and restart the
server straight away; until the restart, sign-ins and token refreshes fail.
Existing ServiceNow access tokens keep working until they expire.

**Metrics token.** List both tokens (`<new>,<old>`), switch the scraper to the
new one, then remove the old one. Scrapes never fail during the change.

## Revocation and offboarding

| Situation | What to do | Takes effect |
| --- | --- | --- |
| A client signs out | The client calls `/revoke` (RFC 7009) with its token. The broker revokes both ServiceNow tokens behind the grant and deletes the grant. | Immediately, for that grant |
| A user leaves or is compromised | Deactivate the user in ServiceNow, or revoke their tokens under **System OAuth > Manage Tokens**. | On their next request: every request re-checks the token with ServiceNow |
| Stop a client from connecting | Remove its URL from `POC_APPROVED_CLIENTS` and restart. | At its next sign-in or token refresh |
| Sign everyone out (emergency) | Stop the server; rotate `POC_SIGNING_KEY`; delete the contents of `POC_STORAGE_DIR`; revoke the OAuth app's tokens in ServiceNow (or deactivate the app); start the server. | Immediately |

- The ServiceNow revocation endpoint is `POC_SERVICENOW_REVOKE_PATH`, default
  `/oauth_revoke_token.do`; confirm it on your instance. If the ServiceNow call
  fails, the broker logs a warning and still deletes the local grant; revoke
  in **Manage Tokens** to be certain. An empty value skips the ServiceNow call.
- `mcp_revocations_total{result}` counts revocation requests. Watch it after
  disconnecting the connector in Claude to confirm whether Claude calls
  `/revoke`; if it does not, disconnecting leaves the ServiceNow grant until it
  expires, and the offboarding steps above are the way to end it.
- The MCP SDK's revocation endpoint requires a `client_secret` form field even
  for public clients, which send it empty. A client that omits it gets `400`.

## Network and health checks

TLS terminates at a reverse proxy or load balancer in front of the container.
It must forward every path (`/mcp`, `/authorize`, `/token`, `/register`,
`/consent`, `/auth/callback`, `/.well-known/*`) and preserve the public `Host`
header, because the server accepts only the host in `POC_PUBLIC_URL` plus the
loopback names `127.0.0.1:<port>` and `localhost:<port>`, and any internal
names listed in `POC_INTERNAL_HOSTS`.

- The image's own `HEALTHCHECK` calls `http://127.0.0.1:8000/healthz` inside the
  container.
- A platform probe or scraper that connects by an internal name must have that
  name in `POC_INTERNAL_HOSTS` (for example `servicenow-mcp:8000`), or send
  `Host: localhost:8000`; otherwise host protection rejects it. An exec probe
  running the same command as the `HEALTHCHECK` also works.

## Logs

The server writes one JSON object per line to stdout, so any platform's log
collector can ship it. Each line has `time` (UTC), `level`, `logger` and
`message`. Lines written while handling a request also carry `request_id`;
incident audit events add an `audit` object, and each request adds one access
line with an `http` object (`method`, `path`, `status`, `duration_ms`).

| Setting | Values | Default |
| --- | --- | --- |
| `POC_LOG_FORMAT` | `json`, or `text` for local reading | `json` |
| `POC_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` |

- **Request IDs:** a well-formed incoming `X-Request-ID` (8–64 letters, digits,
  `.`, `_`, `-`) is kept; otherwise one is generated. Every response returns it
  in `X-Request-ID`, so a user's report can be matched to the log lines.
- **Redaction:** before anything is written, the server removes bearer and basic
  credentials, OAuth codes and state, token, secret and password fields, URL
  query strings, and the authorization codes and transaction IDs that FastMCP's
  OAuth proxy puts in its own messages. Access lines record the path only,
  never the query string, and uvicorn's own access log is off.
- **Third-party loggers:** HTTP client libraries are held at `WARNING`, and
  FastMCP's OAuth proxy at `INFO` even when `POC_LOG_LEVEL=DEBUG`, because their
  debug output includes full URLs and authorization codes.
- The image sets `FASTMCP_CHECK_FOR_UPDATES=off` (no call to PyPI at start-up)
  and `FASTMCP_ENABLE_RICH_LOGGING=false`.

## Monitoring

`GET /metrics` serves Prometheus-format metrics, which most monitoring stacks
can scrape. It is **off unless `POC_METRICS_TOKEN` is set** (it returns 404),
and then requires `Authorization: Bearer <token>`. Store the token in the
secret manager and give it only to the scraper.

| Metric | Labels | Use |
| --- | --- | --- |
| `mcp_http_requests_total` | `route`, `method`, `status` (`2xx`…`5xx`) | Traffic and error rate |
| `mcp_http_request_duration_seconds` | `route` (histogram) | Latency, p95 |
| `mcp_tool_calls_total` | `tool`, `outcome`, `error_code` | Tool usage and failures |
| `servicenow_responses_total` | `status` (`401`, `403`, `404`, `408`, `429`, `2xx`…`5xx`, `no_response`) | ServiceNow health |
| `servicenow_identity_checks_total` | `result` (`valid`, `rejected`, `servicenow_unavailable`) | Sign-in health |
| `mcp_rate_limited_total` | `group` (`mcp`, `sign_in`, `oauth_api`) | Throttled requests |
| `mcp_process_start_time_seconds` | – | Restarts |

Labels are always bounded: unknown paths become `route="other"`, and no
metric carries users, search values, or record identifiers.

Each alert links to its section in the [runbooks](runbooks.md).

Example scrape job (job name `servicenow-mcp`, which the alert rules expect):

```yaml
scrape_configs:
  - job_name: servicenow-mcp
    scheme: http
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/servicenow-mcp-token
    static_configs:
      - targets: ["servicenow-mcp:8000"]
```

The server accepts only known `Host` values, so add the scrape target's name to
`POC_INTERNAL_HOSTS` (comma-separated `host:port`, no wildcards), for example
`POC_INTERNAL_HOSTS=servicenow-mcp:8000`. Starting alert rules are in
[`deploy/monitoring/alerts.yml`](../deploy/monitoring/alerts.yml): server
down, 5xx rate, `/mcp` p95 latency, ServiceNow unavailable, sign-in rejections,
tool error rate, registration spikes, and sustained rate limiting. Tune their thresholds once real
traffic is known.

## Rate limits

Each caller has a per-minute allowance; a request over it gets `429` with
`Retry-After` and is counted in `mcp_rate_limited_total`. Health, metrics and
`/.well-known` discovery routes are never limited.

| Routes | Keyed by | Setting | Default |
| --- | --- | --- | --- |
| `/mcp` | Hash of the caller's bearer token (one allowance per sign-in) | `POC_RATE_LIMIT_MCP_PER_MINUTE` | 120 |
| `/authorize`, `/consent`, `/auth/callback` | Client IP (the user's browser) | `POC_RATE_LIMIT_SIGN_IN_PER_MINUTE` | 30 |
| `/register`, `/token`, `/revoke` | Client IP | `POC_RATE_LIMIT_OAUTH_API_PER_MINUTE` | 300 |

Claude's registration, token and `/mcp` calls come from Anthropic's servers, so
many users share a few addresses: that is why `/mcp` is limited per sign-in and
the OAuth API limit is high, an overall safety net rather than a per-user cap.

Behind a load balancer, the client IP is the balancer's unless the server trusts
its `X-Forwarded-For` header. Set uvicorn's `FORWARDED_ALLOW_IPS` to the
balancer's addresses (comma-separated IPs or CIDR ranges); the default,
`127.0.0.1`, suits a proxy or tunnel on the same host. Without it, all
browsers share one sign-in allowance. Counters live in the process, which
matches the single-replica constraint below.

## Constraints

One process handles about 65 tool calls/s at 200 ms ServiceNow latency; see
[performance](performance.md). Run exactly one replica until shared token storage is in place: the token store
is a file tree on one volume and refresh locking is per process. Keep the
signing and encryption keys stable across restarts and deploys; changing either
signs every user out. CI builds the image on every pull request and checks that
it starts read-only as UID 10001, serves `/healthz`, and still requires sign-in
on `/mcp`.
