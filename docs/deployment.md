# Deploying the remote server

The remote OAuth broker ships as a container image built from the repository's
`Dockerfile`. It is platform-neutral: it reads its configuration from
environment variables, logs to stdout, and keeps its
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

## Constraints

Run exactly one replica until shared token storage is in place: the token store
is a file tree on one volume and refresh locking is per process. Keep the
signing and encryption keys stable across restarts and deploys; changing either
signs every user out. CI builds the image on every pull request and checks that
it starts read-only as UID 10001, serves `/healthz`, and still requires sign-in
on `/mcp`.
