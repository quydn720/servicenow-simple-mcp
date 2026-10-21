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

## Network and health checks

TLS terminates at a reverse proxy or load balancer in front of the container.
It must forward every path (`/mcp`, `/authorize`, `/token`, `/register`,
`/consent`, `/auth/callback`, `/.well-known/*`) and preserve the public `Host`
header, because the server accepts only the host in `POC_PUBLIC_URL` plus the
loopback names `127.0.0.1:<port>` and `localhost:<port>`.

- The image's own `HEALTHCHECK` calls `http://127.0.0.1:8000/healthz` inside the
  container.
- A platform probe that connects to the container's IP must send
  `Host: localhost:8000` (or the public host); otherwise host protection rejects
  it. An exec probe running the same command as the `HEALTHCHECK` also works.

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

## Constraints

Run exactly one replica until shared token storage is in place: the token store
is a file tree on one volume and refresh locking is per process. Keep the
signing and encryption keys stable across restarts and deploys; changing either
signs every user out. CI builds the image on every pull request and checks that
it starts read-only as UID 10001, serves `/healthz`, and still requires sign-in
on `/mcp`.
