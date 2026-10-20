"""Run with python -m servicenow_mcp.servers.remote after configuring .env.remote."""

import os
from urllib.parse import urlparse

from cryptography.fernet import Fernet, MultiFernet
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from servicenow_mcp.config.environment import load_environment
from servicenow_mcp.servers.base import ErrorReportingServer
from key_value.aio.stores.filetree import FileTreeStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from servicenow_mcp.auth.servicenow_remote import create_auth, user_client_factory
from servicenow_mcp.observability.logs import RequestContextMiddleware, configure_logging
from servicenow_mcp.observability.metrics import metrics_endpoint
from servicenow_mcp.servers.rate_limit import RateLimitMiddleware, limits_from_env
from servicenow_mcp.config.remote import RemoteSettings
from servicenow_mcp.config.secrets import split_keys
from servicenow_mcp.tools import service_desk
from servicenow_mcp.tools.common.records import register


def encrypted_storage(settings: RemoteSettings):
    directory = settings.storage_dir.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    return FernetEncryptionWrapper(
        key_value=FileTreeStore(data_directory=directory),
        # Newest key encrypts; every listed key decrypts, so keys rotate
        # without signing users out (docs/deployment.md#secrets).
        fernet=MultiFernet([Fernet(key.encode()) for key in split_keys(settings.encryption_key)]),
        # A grant no listed key can read is treated as absent: that user signs
        # in again instead of hitting a server error.
        raise_on_decryption_error=False,
    )


def create_remote_server(settings: RemoteSettings, *, storage=None, http_client=None):
    auth = create_auth(settings, storage if storage is not None else encrypted_storage(settings), http_client)
    server = ErrorReportingServer(
        "servicenow-user-auth-poc", auth=auth,
        instructions="Read-only ServiceNow tools for records, incidents, published knowledge "
        "summaries, and change status. No create, update, or confirmation tools exist. "
        "ServiceNow enforces the connected user's ACLs.",
    )
    client_factory = user_client_factory(settings)
    register(server, client_factory)

    server.custom_route("/metrics", methods=["GET"], include_in_schema=False)(metrics_endpoint)

    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(request):
        # Liveness only: no ServiceNow call, no storage access, no details.
        return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})

    # Write previews are session-bound and unsupported over stateless HTTP.
    service_desk.register_reads(server, client_factory)
    return server


def bind_address() -> tuple[str, int]:
    """Listen address; containers set POC_BIND_HOST=0.0.0.0 behind their proxy."""
    host = os.getenv("POC_BIND_HOST", "127.0.0.1").strip()
    port = os.getenv("POC_BIND_PORT", "8000").strip()
    if not host or any(c.isspace() for c in host):
        raise ValueError("POC_BIND_HOST must be a host name or IP address")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("POC_BIND_PORT must be a port number from 1 to 65535")
    return host, int(port)


def internal_hosts() -> list[str]:
    """Extra Host values for in-network callers such as scrapers and probes."""
    hosts = [h.strip() for h in os.getenv("POC_INTERNAL_HOSTS", "").split(",") if h.strip()]
    for host in hosts:
        name, _, port = host.rpartition(":")
        if not name or not port.isdigit() or "*" in host or "/" in host or any(c.isspace() for c in host):
            raise ValueError("POC_INTERNAL_HOSTS must be comma-separated host:port values without wildcards")
    return hosts


def main():
    load_environment(remote=True)
    configure_logging()
    settings = RemoteSettings.from_env()
    host, port = bind_address()
    # Single worker, persistent encrypted state. TLS terminates at the proxy.
    os.umask(0o077)
    server = create_remote_server(settings)
    server.run(
        transport="http", host=host, port=port, path="/mcp", show_banner=False,
        # Outermost first: every request, including a refused one, gets an ID,
        # an access line, and metrics.
        middleware=[Middleware(RequestContextMiddleware),
                    Middleware(RateLimitMiddleware, limits=limits_from_env())],
        stateless_http=True, json_response=True,
        # OAuth callbacks carry authorization codes in their query string, so
        # uvicorn's access log stays off; the middleware logs one line per
        # request without the query. log_config=None keeps uvicorn on the
        # redacting root handler.
        uvicorn_config={"access_log": False, "log_config": None},
        host_origin_protection=True,
        # Local health checks use the loopback names and in-network callers the
        # names in POC_INTERNAL_HOSTS; everything else must use the public host.
        allowed_hosts=[urlparse(settings.public_url).netloc, f"127.0.0.1:{port}", f"localhost:{port}",
                       *internal_hosts()],
        allowed_origins=[settings.public_url],
    )


if __name__ == "__main__":
    main()
