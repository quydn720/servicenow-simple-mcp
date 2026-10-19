"""Run with python -m servicenow_mcp.servers.remote after configuring .env.remote."""

import os
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from starlette.responses import JSONResponse
from servicenow_mcp.config.environment import load_environment
from servicenow_mcp.servers.base import ErrorReportingServer
from key_value.aio.stores.filetree import FileTreeStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from servicenow_mcp.auth.servicenow_remote import create_auth, user_client_factory
from servicenow_mcp.config.remote import RemoteSettings
from servicenow_mcp.tools import service_desk
from servicenow_mcp.tools.common.records import register


def encrypted_storage(settings: RemoteSettings):
    directory = settings.storage_dir.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    return FernetEncryptionWrapper(
        key_value=FileTreeStore(data_directory=directory),
        fernet=Fernet(settings.encryption_key.encode()),
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


def main():
    load_environment(remote=True)
    settings = RemoteSettings.from_env()
    host, port = bind_address()
    # Single worker, persistent encrypted state. TLS terminates at the proxy.
    os.umask(0o077)
    server = create_remote_server(settings)
    server.run(
        transport="http", host=host, port=port, path="/mcp",
        stateless_http=True, json_response=True,
        # OAuth callbacks include authorization codes in their query string.
        uvicorn_config={"access_log": False},
        host_origin_protection=True,
        # Local health checks use the loopback names; everything else must
        # arrive with the public host name.
        allowed_hosts=[urlparse(settings.public_url).netloc, f"127.0.0.1:{port}", f"localhost:{port}"],
        allowed_origins=[settings.public_url],
    )


if __name__ == "__main__":
    main()
