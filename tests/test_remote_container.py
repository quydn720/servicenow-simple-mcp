"""Container entry point: bind address, health endpoint, and image hardening."""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from key_value.aio.stores.memory import MemoryStore
from starlette.testclient import TestClient

from servicenow_mcp.config.remote import RemoteSettings
from servicenow_mcp.servers import remote as remote_module
from servicenow_mcp.servers.remote import bind_address, create_remote_server

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings(tmp_path):
    return RemoteSettings(
        "https://instance.example.com", "https://mcp.example.com", "mcp-app",
        "upstream-secret", "s" * 64, Fernet.generate_key().decode(),
        ("http://127.0.0.1:8766/callback",), storage_dir=tmp_path / "tokens",
    )


def app_for(settings, hosts):
    server = create_remote_server(settings, storage=MemoryStore())
    return server.http_app(path="/mcp", stateless_http=True, json_response=True,
                           host_origin_protection=True, allowed_hosts=hosts,
                           allowed_origins=[settings.public_url])


def test_healthz_needs_no_sign_in_and_reveals_nothing(settings):
    app = app_for(settings, ["mcp.example.com", "127.0.0.1:8000"])
    with TestClient(app, base_url="https://mcp.example.com") as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        assert health.headers["cache-control"] == "no-store"
        # The MCP endpoint itself still requires a sign-in.
        assert client.post("/mcp", json={}).status_code == 401


def test_container_health_check_host_is_allowed(settings):
    app = app_for(settings, ["mcp.example.com", "127.0.0.1:8000", "localhost:8000"])
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/healthz").status_code == 200


@pytest.mark.parametrize("env,expected", [
    ({}, ("127.0.0.1", 8000)),
    ({"MCP_BIND_HOST": "0.0.0.0", "MCP_BIND_PORT": "8080"}, ("0.0.0.0", 8080)),
])
def test_bind_address(monkeypatch, env, expected):
    monkeypatch.delenv("MCP_BIND_HOST", raising=False)
    monkeypatch.delenv("MCP_BIND_PORT", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert bind_address() == expected


@pytest.mark.parametrize("env", [{"MCP_BIND_PORT": "0"}, {"MCP_BIND_PORT": "70000"},
                                 {"MCP_BIND_PORT": "80a"}, {"MCP_BIND_HOST": "a b"}])
def test_invalid_bind_address(monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        bind_address()


def test_main_binds_configured_address_and_allows_only_known_hosts(monkeypatch, settings):
    calls = {}

    class FakeServer:
        def run(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setattr(remote_module, "load_environment", lambda remote: None)
    monkeypatch.setattr(RemoteSettings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(remote_module, "create_remote_server", lambda s: FakeServer())
    monkeypatch.setenv("MCP_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_BIND_PORT", "9000")
    monkeypatch.setenv("MCP_INTERNAL_HOSTS", "servicenow-mcp:9000")
    remote_module.main()
    assert (calls["host"], calls["port"]) == ("0.0.0.0", 9000)
    assert calls["allowed_hosts"] == ["mcp.example.com", "127.0.0.1:9000", "localhost:9000",
                                      "servicenow-mcp:9000"]
    assert calls["uvicorn_config"] == {"access_log": False, "log_config": None}


def test_image_runs_as_non_root_and_ships_no_secrets():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "USER 10001:10001" in dockerfile
    assert "HEALTHCHECK" in dockerfile and "/healthz" in dockerfile
    assert ".env" not in dockerfile.replace(".env.remote", "")
    ignored = (ROOT / ".dockerignore").read_text().splitlines()
    for path in (".env", ".env.*", ".mcp-tokens", ".venv"):
        assert path in ignored


@pytest.mark.parametrize("value,expected", [
    ("", []), ("servicenow-mcp:8000", ["servicenow-mcp:8000"]),
    (" a.internal:8000 , b:9000 ", ["a.internal:8000", "b:9000"]),
])
def test_internal_hosts(monkeypatch, value, expected):
    monkeypatch.setenv("MCP_INTERNAL_HOSTS", value)
    assert remote_module.internal_hosts() == expected


@pytest.mark.parametrize("value", ["*:8000", "servicenow-mcp", "a b:80", "host:80/x", ":8000"])
def test_invalid_internal_hosts(monkeypatch, value):
    monkeypatch.setenv("MCP_INTERNAL_HOSTS", value)
    with pytest.raises(ValueError):
        remote_module.internal_hosts()
