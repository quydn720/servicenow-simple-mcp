"""Environment profile: test and production refuse insecure remote settings."""

import logging
from dataclasses import replace
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet

from servicenow_mcp.cli import check_remote
from servicenow_mcp.config.remote import RemoteSettings
from servicenow_mcp.config.secrets import SECRET_SETTINGS, secret_source

KEY = Fernet.generate_key().decode()


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in SECRET_SETTINGS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"{name}_FILE", raising=False)
    for name in ("MCP_ENVIRONMENT", "MCP_SERVICENOW_SCOPE", "MCP_ALLOW_DYNAMIC_REGISTRATION",
                 "MCP_SERVICENOW_REVOKE_PATH", "MCP_APPROVED_CLIENTS"):
        monkeypatch.delenv(name, raising=False)
    remote_env = tmp_path / ".env.remote"
    remote_env.write_text("")
    monkeypatch.setenv("MCP_REMOTE_ENV_FILE", str(remote_env))
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    for name, value in {"MCP_SERVICENOW_CLIENT_SECRET": "client-secret", "MCP_SIGNING_KEY": "k" * 48,
                        "MCP_ENCRYPTION_KEY": KEY}.items():
        (secrets / name).write_text(value)
        monkeypatch.setenv(f"{name}_FILE", str(secrets / name))
    for name, value in {"MCP_SERVICENOW_INSTANCE": "https://instance.example.com",
                        "MCP_PUBLIC_URL": "https://mcp.example.com", "MCP_SERVICENOW_CLIENT_ID": "app",
                        "MCP_ALLOWED_REDIRECT_URIS": "https://claude.ai/api/mcp/auth_callback", "MCP_IDENTITY_PATH": "/api/x_mcp/identity/me",
                        "MCP_SERVICENOW_SCOPE": "mcp_read"}.items():
        monkeypatch.setenv(name, value)
    return remote_env


@pytest.mark.parametrize("environment", ["test", "production"])
def test_compliant_settings_start_in_enforced_environments(env, monkeypatch, environment):
    monkeypatch.setenv("MCP_ENVIRONMENT", environment)
    settings = RemoteSettings.from_env()
    assert settings.environment == environment
    assert settings.policy_violations() == []
    assert set(settings.secret_sources.values()) == {"file"}


@pytest.mark.parametrize("change,message", [
    ({"MCP_SERVICENOW_SCOPE": ""}, "MCP_SERVICENOW_SCOPE"),
    ({"MCP_ALLOW_DYNAMIC_REGISTRATION": "true"}, "MCP_ALLOW_DYNAMIC_REGISTRATION"),
    ({"MCP_SERVICENOW_REVOKE_PATH": ""}, "MCP_SERVICENOW_REVOKE_PATH"),
])
@pytest.mark.parametrize("environment", ["test", "production"])
def test_insecure_settings_are_refused_outside_development(env, monkeypatch, environment, change, message):
    monkeypatch.setenv("MCP_ENVIRONMENT", environment)
    for name, value in change.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        RemoteSettings.from_env()


def test_secret_written_in_the_env_file_is_refused_in_production(env, monkeypatch):
    monkeypatch.setenv("MCP_ENVIRONMENT", "production")
    monkeypatch.delenv("MCP_SIGNING_KEY_FILE")
    monkeypatch.setenv("MCP_SIGNING_KEY", "k" * 48)
    env.write_text("MCP_SIGNING_KEY=" + "k" * 48 + "\n")
    assert secret_source("MCP_SIGNING_KEY") == "dotenv"
    with pytest.raises(ValueError, match="MCP_SIGNING_KEY is plain text"):
        RemoteSettings.from_env()


def test_secret_injected_by_the_platform_is_accepted(env, monkeypatch):
    monkeypatch.setenv("MCP_ENVIRONMENT", "production")
    monkeypatch.delenv("MCP_SIGNING_KEY_FILE")
    monkeypatch.setenv("MCP_SIGNING_KEY", "k" * 48)  # not written in .env.remote
    assert RemoteSettings.from_env().secret_sources["MCP_SIGNING_KEY"] == "environment"


def test_tunnel_hosts_are_refused_only_in_production(env, monkeypatch):
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://pilot.ngrok-free.dev")
    monkeypatch.setenv("MCP_ENVIRONMENT", "test")
    assert RemoteSettings.from_env().policy_violations() == []
    monkeypatch.setenv("MCP_ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="tunnel host"):
        RemoteSettings.from_env()


def test_development_warns_but_starts(env, monkeypatch, caplog):
    monkeypatch.setenv("MCP_SERVICENOW_SCOPE", "")
    caplog.set_level(logging.WARNING)
    settings = RemoteSettings.from_env()
    assert settings.environment == "development"
    assert "MCP_SERVICENOW_SCOPE" in caplog.text


def test_unknown_environment_is_rejected(env, monkeypatch):
    monkeypatch.setenv("MCP_ENVIRONMENT", "staging")
    with pytest.raises(ValueError, match="MCP_ENVIRONMENT"):
        RemoteSettings.from_env()


# --- servicenow-mcp-check-remote ---------------------------------------------

def settings_for(environment="production", **changes):
    base = RemoteSettings(
        "https://instance.example.com", "https://mcp.example.com", "app", "client-secret", "k" * 48, KEY,
        ("https://claude.ai/api/mcp/auth_callback",), servicenow_scope="mcp_read",
        environment=environment, secret_sources={"MCP_SIGNING_KEY": "file"})
    return replace(base, **changes)


def fake_http(authorize=(302, ""), identity=401, metadata=None, mcp=401, down=False):
    import requests
    http = Mock()

    def get(url, **kwargs):
        if down:
            raise requests.ConnectionError()
        if url.endswith("/oauth_auth.do"):
            http.authorize_params = kwargs["params"]
            return Mock(status_code=authorize[0], text=authorize[1])
        if url.endswith("/.well-known/oauth-authorization-server"):
            return Mock(json=Mock(return_value=metadata if metadata is not None
                                  else {"revocation_endpoint": "https://mcp.example.com/revoke"}))
        return Mock(status_code=identity)

    http.get.side_effect = get
    http.post.return_value = Mock(status_code=mcp)
    return http


def results(checks):
    return {(c.area, c.name): c.result for c in checks}


def test_servicenow_checks_pass_for_a_recognized_client_and_protected_identity_api():
    http = fake_http()
    checks = results(check_remote.servicenow_checks(settings_for(), http))
    assert checks == {("servicenow", "OAuth client"): "PASS", ("servicenow", "identity API"): "PASS"}
    assert http.authorize_params["scope"] == "mcp_read"
    assert http.authorize_params["redirect_uri"] == "https://mcp.example.com/auth/callback"


@pytest.mark.parametrize("kwargs,name", [
    ({"authorize": (401, "error=unauthorized_client")}, "OAuth client"),
    ({"identity": 200}, "identity API"),
])
def test_servicenow_misconfiguration_fails(kwargs, name):
    checks = results(check_remote.servicenow_checks(settings_for(), fake_http(**kwargs)))
    assert checks[("servicenow", name)] == "FAIL"


def test_broker_checks_cover_registration_revocation_and_sign_in():
    good = results(check_remote.broker_checks(settings_for(), fake_http()))
    assert set(good.values()) == {"PASS"}
    bad = results(check_remote.broker_checks(settings_for(), fake_http(
        metadata={"registration_endpoint": "https://mcp.example.com/register"}, mcp=200)))
    assert bad[("broker", "registration")] == "FAIL"
    assert bad[("broker", "revocation")] == "FAIL"
    assert bad[("broker", "sign-in required")] == "FAIL"


def test_unreachable_broker_is_a_warning_not_a_failure():
    assert results(check_remote.broker_checks(settings_for(), fake_http(down=True))) == {
        ("broker", "reachable"): "WARN"}


def test_plain_text_secrets_warn_in_development_and_fail_when_enforced():
    dev = settings_for("development", secret_sources={"MCP_SIGNING_KEY": "dotenv"})
    prod = settings_for("production", secret_sources={"MCP_SIGNING_KEY": "dotenv"})
    assert results(check_remote.settings_checks(dev))[("settings", "MCP_SIGNING_KEY")] == "WARN"
    assert results(check_remote.settings_checks(prod))[("settings", "MCP_SIGNING_KEY")] == "FAIL"


def test_refused_settings_are_reported_as_one_failure(env, monkeypatch, capsys):
    monkeypatch.setenv("MCP_ENVIRONMENT", "production")
    monkeypatch.setenv("MCP_SERVICENOW_SCOPE", "")
    assert check_remote.main(["--offline", "--json"]) == 1
    assert "MCP_SERVICENOW_SCOPE" in capsys.readouterr().out


def test_offline_run_passes_with_compliant_settings(env, monkeypatch):
    monkeypatch.setenv("MCP_ENVIRONMENT", "production")
    checks, code = check_remote.run(offline=True)
    assert code == 0
    assert not any(c.area in ("servicenow", "broker") for c in checks)


def test_identity_path_is_required(env, monkeypatch):
    monkeypatch.delenv("MCP_IDENTITY_PATH")
    with pytest.raises(ValueError, match="MCP_IDENTITY_PATH"):
        RemoteSettings.from_env()
