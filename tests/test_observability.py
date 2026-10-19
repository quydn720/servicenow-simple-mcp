"""Redacted structured logs and request IDs for the remote server."""

import json
import logging

import pytest
from cryptography.fernet import Fernet
from key_value.aio.stores.memory import MemoryStore
from starlette.middleware import Middleware
from starlette.testclient import TestClient

from servicenow_mcp.config.remote import RemoteSettings
from servicenow_mcp.observability import logs
from servicenow_mcp.observability.logs import (
    JsonFormatter, RequestContextMiddleware, configure_logging, redact,
)
from servicenow_mcp.servers import remote as remote_module
from servicenow_mcp.servers.remote import create_remote_server


@pytest.fixture(autouse=True)
def restore_logging():
    """configure_logging changes global loggers; put every one back afterwards."""
    names = ["", "fastmcp", "mcp", "uvicorn", "uvicorn.error", "uvicorn.access",
             "fastmcp.server.auth", "httpx", "httpx2", "httpcore", "authlib"]
    saved = {n: (logging.getLogger(n).handlers[:], logging.getLogger(n).propagate,
                 logging.getLogger(n).level) for n in names}
    yield
    for n, (handlers, propagate, level) in saved.items():
        target = logging.getLogger(n)
        target.handlers[:], target.propagate, target.level = handlers, propagate, level


@pytest.mark.parametrize("text,secret", [
    ("GET https://mcp.example.com/auth/callback?code=abc123&state=xyz789", "abc123"),
    ("GET https://mcp.example.com/auth/callback?code=abc123&state=xyz789", "xyz789"),
    ("Authorization: Bearer sn-token-value", "sn-token-value"),
    ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
    ("refresh_token=rt-secret&grant_type=refresh_token", "rt-secret"),
    ('{"access_token": "at-secret", "expires_in": 1800}', "at-secret"),
    ("client_secret=shh; next", "shh"),
    ("IdP callback with invalid transaction ID: Abc123def456ghi", "Abc123def456ghi"),
    ("Transaction Abc123def456ghi missing consent_token", "Abc123def456ghi"),
    ("Forwarding to client callback for transaction Abc123def456ghi", "Abc123def456ghi"),
    ("Authorization code not found: mcp-code-0123456789", "mcp-code-0123456789"),
    ("Authorization code expired: mcp-code-0123456789", "mcp-code-0123456789"),
])
def test_redact_removes_secrets(text, secret):
    assert secret not in redact(text)
    assert "[REDACTED]" in redact(text)


def test_redact_keeps_ordinary_text():
    text = "list_incidents returned 3 records; error_code=PERMISSION_DENIED path=/mcp"
    assert redact(text) == text


def test_json_formatter_emits_one_object_with_request_id_and_audit():
    record = logging.LogRecord("servicenow_mcp.test", logging.INFO, __file__, 1,
                               "callback https://x.example/cb?code=%s", ("c0de-value",), None)
    record.incident_search_audit = {"event": "incident_search", "identity": "a" * 32}
    token = logs.REQUEST_ID.set("req-12345678")
    try:
        entry = json.loads(JsonFormatter().format(record))
    finally:
        logs.REQUEST_ID.reset(token)
    assert entry["level"] == "INFO" and entry["logger"] == "servicenow_mcp.test"
    assert entry["request_id"] == "req-12345678"
    assert entry["audit"] == {"event": "incident_search", "identity": "a" * 32}
    assert "c0de-value" not in entry["message"]


def test_exceptions_are_logged_redacted():
    try:
        raise RuntimeError("token exchange failed for refresh_token=rt-leak")
    except RuntimeError:
        import sys
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    entry = json.loads(JsonFormatter().format(record))
    assert "rt-leak" not in entry["exception"] and "RuntimeError" in entry["exception"]


@pytest.fixture
def app(tmp_path):
    settings = RemoteSettings(
        "https://instance.example.com", "https://mcp.example.com", "poc-app", "upstream-secret",
        "s" * 64, Fernet.generate_key().decode(), ("http://127.0.0.1:8766/callback",),
        storage_dir=tmp_path / "tokens")
    server = create_remote_server(settings, storage=MemoryStore())
    return server.http_app(path="/mcp", stateless_http=True, json_response=True,
                           middleware=[Middleware(RequestContextMiddleware)],
                           host_origin_protection=True, allowed_hosts=["mcp.example.com"],
                           allowed_origins=[settings.public_url])


def test_every_request_gets_an_id_and_one_safe_access_line(app, monkeypatch, capsys):
    monkeypatch.setenv("POC_LOG_FORMAT", "json")
    monkeypatch.setenv("POC_LOG_LEVEL", "INFO")
    configure_logging()  # the same setup main() runs, writing to stdout
    with TestClient(app, base_url="https://mcp.example.com", follow_redirects=False) as client:
        response = client.get("/auth/callback",
                              params={"code": "secret-code-123", "state": "SecretState12345"})
    output = capsys.readouterr().out
    entries = [json.loads(row) for row in output.splitlines()]
    request_id = response.headers["x-request-id"]
    assert len(request_id) == 32
    [line] = [e["http"] for e in entries if "http" in e]
    assert line["method"] == "GET" and line["path"] == "/auth/callback"
    assert line["status"] == response.status_code and line["duration_ms"] >= 0
    # FastMCP logs the rejected state value; the written line must not contain it.
    [callback_error] = [e for e in entries if "transaction" in e["message"]]
    access_line = next(e for e in entries if "http" in e)
    # Lines written while handling the request carry its ID; startup lines do not.
    assert callback_error["request_id"] == access_line["request_id"] == request_id
    assert "secret-code-123" not in output and "SecretState12345" not in output


@pytest.mark.parametrize("incoming,echoed", [("trace-abc-12345", True), ("bad id!", False), ("short", False)])
def test_incoming_request_id_is_used_only_when_well_formed(app, incoming, echoed):
    with TestClient(app, base_url="https://mcp.example.com") as client:
        response = client.get("/healthz", headers={"X-Request-ID": incoming})
    assert (response.headers["x-request-id"] == incoming) is echoed


def test_configure_logging_routes_everything_through_one_redacting_handler(monkeypatch):
    monkeypatch.setenv("POC_LOG_FORMAT", "json")
    monkeypatch.setenv("POC_LOG_LEVEL", "INFO")
    configure_logging()
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    for name in ("fastmcp", "uvicorn.error"):
        assert logging.getLogger(name).handlers == [] and logging.getLogger(name).propagate
    assert logging.getLogger("httpx2").level == logging.WARNING


def test_debug_level_never_reaches_the_oauth_proxy_logger(monkeypatch):
    monkeypatch.setenv("POC_LOG_LEVEL", "DEBUG")
    configure_logging()
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert logging.getLogger("fastmcp.server.auth").getEffectiveLevel() == logging.INFO


@pytest.mark.parametrize("env", [{"POC_LOG_FORMAT": "xml"}, {"POC_LOG_LEVEL": "LOUD"}])
def test_configure_logging_rejects_unknown_settings(monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        configure_logging()


def test_main_installs_the_middleware_and_hides_the_banner(monkeypatch, tmp_path):
    calls = {}

    class FakeServer:
        def run(self, **kwargs):
            calls.update(kwargs)

    settings = RemoteSettings(
        "https://instance.example.com", "https://mcp.example.com", "poc-app", "upstream-secret",
        "s" * 64, Fernet.generate_key().decode(), ("http://127.0.0.1:8766/callback",),
        storage_dir=tmp_path / "tokens")
    monkeypatch.setattr(remote_module, "load_environment", lambda remote: None)
    monkeypatch.setattr(remote_module, "configure_logging", lambda: calls.setdefault("logging", True))
    monkeypatch.setattr(RemoteSettings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(remote_module, "create_remote_server", lambda s: FakeServer())
    remote_module.main()
    assert calls["logging"] is True and calls["show_banner"] is False
    from servicenow_mcp.servers.rate_limit import RateLimitMiddleware
    # Request context is outermost, so refused requests still get an ID and a log line.
    assert [m.cls for m in calls["middleware"]] == [RequestContextMiddleware, RateLimitMiddleware]
