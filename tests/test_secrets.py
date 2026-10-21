"""Secret files and key rotation for the remote server."""

import asyncio
from dataclasses import replace

import pytest
from cryptography.fernet import Fernet
from key_value.aio.stores.memory import MemoryStore
from starlette.testclient import TestClient

from servicenow_mcp.config.remote import RemoteSettings
from servicenow_mcp.config.secrets import SECRET_SETTINGS, read_secret
from servicenow_mcp.servers.remote import create_remote_server, encrypted_storage

OLD, NEW = Fernet.generate_key().decode(), Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in SECRET_SETTINGS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"{name}_FILE", raising=False)


@pytest.fixture
def settings(tmp_path):
    return RemoteSettings(
        "https://instance.example.com", "https://mcp.example.com", "mcp-app", "upstream-secret",
        "s" * 64, OLD, ("https://claude.ai/api/mcp/auth_callback",), storage_dir=tmp_path / "tokens")


def test_secret_from_environment_or_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_SIGNING_KEY", "from-env")
    assert read_secret("MCP_SIGNING_KEY") == "from-env"
    monkeypatch.delenv("MCP_SIGNING_KEY")
    secret_file = tmp_path / "signing_key"
    secret_file.write_text("from-file\n")
    monkeypatch.setenv("MCP_SIGNING_KEY_FILE", str(secret_file))
    assert read_secret("MCP_SIGNING_KEY") == "from-file"


def test_both_sources_is_an_error(tmp_path, monkeypatch):
    secret_file = tmp_path / "s"
    secret_file.write_text("x")
    monkeypatch.setenv("MCP_SIGNING_KEY", "y")
    monkeypatch.setenv("MCP_SIGNING_KEY_FILE", str(secret_file))
    with pytest.raises(ValueError, match="not both"):
        read_secret("MCP_SIGNING_KEY")


@pytest.mark.parametrize("content", [None, "", "   \n"])
def test_missing_or_empty_files_are_errors_without_leaking_contents(tmp_path, monkeypatch, content):
    path = tmp_path / "secret"
    if content is not None:
        path.write_text(content)
    monkeypatch.setenv("MCP_SIGNING_KEY_FILE", str(path))
    with pytest.raises(ValueError, match="MCP_SIGNING_KEY_FILE"):
        read_secret("MCP_SIGNING_KEY")


def test_optional_secret_may_be_absent():
    assert read_secret("MCP_METRICS_TOKEN", required=False) == ""
    with pytest.raises(ValueError, match="MCP_SIGNING_KEY"):
        read_secret("MCP_SIGNING_KEY")


def test_settings_load_every_secret_from_files(tmp_path, monkeypatch, settings):
    files = {"MCP_SERVICENOW_CLIENT_SECRET": "client-secret-value", "MCP_SIGNING_KEY": "k" * 48,
             "MCP_ENCRYPTION_KEY": f"{NEW},{OLD}"}
    for name, value in files.items():
        (tmp_path / name).write_text(value + "\n")
        monkeypatch.setenv(f"{name}_FILE", str(tmp_path / name))
    for name, value in {"MCP_SERVICENOW_INSTANCE": settings.instance, "MCP_PUBLIC_URL": settings.public_url,
                        "MCP_SERVICENOW_CLIENT_ID": "mcp-app",
                        "MCP_ALLOWED_REDIRECT_URIS": "https://claude.ai/api/mcp/auth_callback", "MCP_IDENTITY_PATH": "/api/x_mcp/identity/me"}.items():
        monkeypatch.setenv(name, value)
    loaded = RemoteSettings.from_env()
    assert loaded.client_secret == "client-secret-value"
    assert loaded.signing_key == "k" * 48
    assert loaded.encryption_key == f"{NEW},{OLD}"


@pytest.mark.parametrize("value", ["", ",", f"{NEW},not-a-key"])
def test_invalid_encryption_key_lists_are_rejected(settings, value):
    with pytest.raises(ValueError):
        replace(settings, encryption_key=value)


def test_encryption_key_rotates_without_losing_sign_ins(settings):
    async def run():
        await encrypted_storage(settings).put("grant", {"refresh_token": "kept"})
        # Step 1: deploy the new key first, the old one still listed.
        rotating = encrypted_storage(replace(settings, encryption_key=f"{NEW},{OLD}"))
        assert await rotating.get("grant") == {"refresh_token": "kept"}
        await rotating.put("grant", {"refresh_token": "rewritten"})  # re-encrypted with NEW
        await rotating.put("fresh", {"refresh_token": "new"})
        # Step 2: drop the old key; everything rewritten since is still readable.
        rotated = encrypted_storage(replace(settings, encryption_key=NEW))
        assert await rotated.get("grant") == {"refresh_token": "rewritten"}
        assert await rotated.get("fresh") == {"refresh_token": "new"}

    asyncio.run(run())


def test_dropping_a_key_too_early_fails_closed(settings):
    async def run():
        await encrypted_storage(settings).put("grant", {"refresh_token": "old"})
        # Unreadable grants count as absent: the user signs in again, no 500.
        assert await encrypted_storage(replace(settings, encryption_key=NEW)).get("grant") is None

    asyncio.run(run())


@pytest.fixture
def client(settings):
    server = create_remote_server(settings, storage=MemoryStore())
    app = server.http_app(path="/mcp", stateless_http=True, json_response=True,
                          host_origin_protection=True, allowed_hosts=["mcp.example.com"],
                          allowed_origins=[settings.public_url])
    with TestClient(app, base_url="https://mcp.example.com") as test_client:
        yield test_client


def test_metrics_token_from_a_file_with_two_tokens_during_rotation(tmp_path, monkeypatch, client):
    token_file = tmp_path / "metrics_token"
    token_file.write_text("new-token, old-token")
    monkeypatch.setenv("MCP_METRICS_TOKEN_FILE", str(token_file))
    for token in ("new-token", "old-token"):
        assert client.get("/metrics", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/metrics", headers={"Authorization": "Bearer other"}).status_code == 401


def test_unreadable_metrics_token_file_fails_closed(tmp_path, monkeypatch, client):
    monkeypatch.setenv("MCP_METRICS_TOKEN_FILE", str(tmp_path / "missing"))
    assert client.get("/metrics", headers={"Authorization": "Bearer x"}).status_code == 503
