"""Only approved MCP clients may sign in to the remote server."""

import asyncio
from dataclasses import replace

import pytest
from cryptography.fernet import Fernet
from fastmcp.server.auth import OAuthProxy
from key_value.aio.stores.memory import MemoryStore
from starlette.testclient import TestClient

from servicenow_mcp.auth.servicenow_remote import ServiceNowOAuthProxy, create_auth
from servicenow_mcp.config.remote import CLAUDE_CLIENT_ID, RemoteSettings
from servicenow_mcp.servers.remote import create_remote_server

UNAPPROVED = "https://evil.example/oauth/client.json"


@pytest.fixture
def settings(tmp_path):
    return RemoteSettings(
        "https://instance.example.com", "https://mcp.example.com", "mcp-app", "upstream-secret",
        "s" * 64, Fernet.generate_key().decode(), ("https://claude.ai/api/mcp/auth_callback",),
        storage_dir=tmp_path / "tokens")


def test_defaults_approve_only_claude_and_disable_registration(settings):
    assert settings.approved_clients == (CLAUDE_CLIENT_ID,)
    assert settings.allow_dynamic_registration is False


def lookup(settings, client_id, monkeypatch):
    fetched = []

    async def parent_get_client(self, cid):
        fetched.append(cid)
        return "client-record"

    monkeypatch.setattr(OAuthProxy, "get_client", parent_get_client)
    auth = create_auth(settings, MemoryStore())
    assert isinstance(auth, ServiceNowOAuthProxy)
    return asyncio.run(auth.get_client(client_id)), fetched


def test_approved_metadata_url_is_served(settings, monkeypatch):
    assert lookup(settings, CLAUDE_CLIENT_ID, monkeypatch) == ("client-record", [CLAUDE_CLIENT_ID])


def test_unapproved_metadata_url_is_rejected_without_being_fetched(settings, monkeypatch):
    assert lookup(settings, UNAPPROVED, monkeypatch) == (None, [])


@pytest.mark.parametrize("registration", [False, True])
def test_the_servicenow_client_id_is_never_an_implicit_client(settings, monkeypatch, registration):
    scoped = replace(settings, allow_dynamic_registration=registration)
    assert lookup(scoped, "mcp-app", monkeypatch) == (None, [])


def test_registered_ids_work_only_when_registration_is_enabled(settings, monkeypatch):
    assert lookup(settings, "dcr-client-123", monkeypatch) == (None, [])
    enabled = replace(settings, allow_dynamic_registration=True)
    assert lookup(enabled, "dcr-client-123", monkeypatch) == ("client-record", ["dcr-client-123"])


def http_client(settings):
    server = create_remote_server(settings, storage=MemoryStore())
    app = server.http_app(path="/mcp", stateless_http=True, json_response=True,
                          host_origin_protection=True, allowed_hosts=["mcp.example.com"],
                          allowed_origins=[settings.public_url])
    return TestClient(app, base_url="https://mcp.example.com", follow_redirects=False)


def test_registration_is_absent_from_routes_and_metadata_by_default(settings):
    with http_client(settings) as client:
        metadata = client.get("/.well-known/oauth-authorization-server").json()
        response = client.post("/register", json={"client_name": "x", "redirect_uris": [
            "https://claude.ai/api/mcp/auth_callback"]})
    assert "registration_endpoint" not in metadata
    assert metadata.get("client_id_metadata_document_supported") is True
    assert response.status_code in (404, 405)


def test_registration_returns_when_enabled(settings):
    with http_client(replace(settings, allow_dynamic_registration=True)) as client:
        metadata = client.get("/.well-known/oauth-authorization-server").json()
    assert metadata["registration_endpoint"].endswith("/register")


@pytest.mark.parametrize("client_id", [UNAPPROVED, "mcp-app", "unknown-dcr-id"])
def test_authorize_refuses_unapproved_clients(settings, client_id):
    with http_client(settings) as client:
        response = client.get("/authorize", params={
            "client_id": client_id, "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "response_type": "code", "state": "s", "code_challenge": "x" * 43,
            "code_challenge_method": "S256"})
    assert response.status_code == 400
    assert "location" not in response.headers


@pytest.mark.parametrize("changes", [
    {"approved_clients": ("http://claude.ai/oauth/mcp-oauth-client-metadata",)},
    {"approved_clients": ("https://*.example.com/client.json",)},
    {"approved_clients": ("https://example.com/",)},
    {"approved_clients": ()},
])
def test_invalid_client_policies_are_rejected(settings, changes):
    with pytest.raises(ValueError):
        replace(settings, **changes)


def test_registration_alone_is_a_valid_policy(settings):
    assert replace(settings, approved_clients=(), allow_dynamic_registration=True)


def test_policy_from_environment(settings, monkeypatch):
    base = {"MCP_SERVICENOW_INSTANCE": settings.instance, "MCP_PUBLIC_URL": settings.public_url,
            "MCP_SERVICENOW_CLIENT_ID": "mcp-app", "MCP_SERVICENOW_CLIENT_SECRET": "upstream-secret",
            "MCP_SIGNING_KEY": settings.signing_key, "MCP_ENCRYPTION_KEY": settings.encryption_key,
            "MCP_ALLOWED_REDIRECT_URIS": "https://claude.ai/api/mcp/auth_callback", "MCP_IDENTITY_PATH": "/api/x_mcp/identity/me"}
    for name, value in base.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("MCP_APPROVED_CLIENTS", raising=False)
    monkeypatch.delenv("MCP_ALLOW_DYNAMIC_REGISTRATION", raising=False)
    assert RemoteSettings.from_env().approved_clients == (CLAUDE_CLIENT_ID,)
    monkeypatch.setenv("MCP_APPROVED_CLIENTS", f"{CLAUDE_CLIENT_ID}, https://other.example/client.json")
    monkeypatch.setenv("MCP_ALLOW_DYNAMIC_REGISTRATION", "true")
    loaded = RemoteSettings.from_env()
    assert loaded.approved_clients == (CLAUDE_CLIENT_ID, "https://other.example/client.json")
    assert loaded.allow_dynamic_registration is True
    monkeypatch.setenv("MCP_ALLOW_DYNAMIC_REGISTRATION", "yes")
    with pytest.raises(ValueError):
        RemoteSettings.from_env()
