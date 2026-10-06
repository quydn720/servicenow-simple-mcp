"""Run with python -m servicenow_mcp.servers.remote after configuring .env.remote."""

import os
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from servicenow_mcp.config.environment import load_environment
from fastmcp import FastMCP
from key_value.aio.stores.filetree import FileTreeStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from servicenow_mcp.auth.servicenow_remote import create_auth, user_client_factory
from servicenow_mcp.config.remote import RemoteSettings
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
    server = FastMCP("servicenow-user-auth-poc", auth=auth,
                     instructions="Read-only ServiceNow tools. ServiceNow enforces the connected user's ACLs.")
    register(server, user_client_factory(settings))
    return server


def main():
    load_environment(remote=True)
    settings = RemoteSettings.from_env()
    # Single worker, persistent encrypted state. TLS terminates at the proxy.
    os.umask(0o077)
    server = create_remote_server(settings)
    server.run(
        transport="http", host="127.0.0.1", port=8000, path="/mcp",
        stateless_http=True, json_response=True,
        # OAuth callbacks include authorization codes in their query string.
        uvicorn_config={"access_log": False},
        host_origin_protection=True,
        allowed_hosts=[urlparse(settings.public_url).netloc, "127.0.0.1:8000"],
        allowed_origins=[settings.public_url],
    )


if __name__ == "__main__":
    main()
