"""Prometheus-format metrics: bounded labels, protected endpoint, and the hooks."""

import asyncio
from unittest.mock import Mock

import httpx2
import pytest
import requests
from cryptography.fernet import Fernet
from fastmcp import Client
from key_value.aio.stores.memory import MemoryStore
from starlette.middleware import Middleware
from starlette.testclient import TestClient

from servicenow_mcp.auth.servicenow_remote import ServiceNowTokenVerifier
from servicenow_mcp.client import ServiceNowClient
from servicenow_mcp.config.local import Settings
from servicenow_mcp.config.remote import RemoteSettings
from servicenow_mcp.observability.logs import RequestContextMiddleware
from servicenow_mcp.observability.metrics import REGISTRY, Registry, route_label
from servicenow_mcp.servers.remote import create_remote_server
from servicenow_mcp.servers.stdio import create_server

ID = "a" * 32


def count(name, **labels):
    return REGISTRY._counters.get((name, tuple(sorted(labels.items()))), 0)


@pytest.fixture
def settings(tmp_path):
    return RemoteSettings(
        "https://instance.example.com", "https://mcp.example.com", "poc-app", "upstream-secret",
        "s" * 64, Fernet.generate_key().decode(), ("http://127.0.0.1:8766/callback",),
        storage_dir=tmp_path / "tokens")


@pytest.fixture
def app(settings):
    server = create_remote_server(settings, storage=MemoryStore())
    return server.http_app(path="/mcp", stateless_http=True, json_response=True,
                           middleware=[Middleware(RequestContextMiddleware)],
                           host_origin_protection=True, allowed_hosts=["mcp.example.com"],
                           allowed_origins=[settings.public_url])


def test_registry_renders_counters_and_cumulative_histograms():
    registry = Registry()
    registry.inc("mcp_tool_calls_total", tool="get_record", outcome="success", error_code="none")
    registry.observe("mcp_http_request_duration_seconds", 0.3, route="/mcp")
    registry.observe("mcp_http_request_duration_seconds", 3.0, route="/mcp")
    text = registry.render()
    assert '# TYPE mcp_tool_calls_total counter' in text
    assert 'mcp_tool_calls_total{error_code="none",outcome="success",tool="get_record"} 1' in text
    assert 'mcp_http_request_duration_seconds_bucket{route="/mcp",le="0.25"} 0' in text
    assert 'mcp_http_request_duration_seconds_bucket{route="/mcp",le="0.5"} 1' in text
    assert 'mcp_http_request_duration_seconds_bucket{route="/mcp",le="+Inf"} 2' in text
    assert 'mcp_http_request_duration_seconds_count{route="/mcp"} 2' in text
    assert "mcp_process_start_time_seconds" in text


@pytest.mark.parametrize("path,label", [("/mcp", "/mcp"), ("/auth/callback", "/auth/callback"),
                                        ("/mcp/../x", "other"), ("/INC0012345", "other")])
def test_routes_are_bounded(path, label):
    assert route_label(path) == label


def test_metrics_endpoint_is_hidden_without_a_token(app, monkeypatch):
    monkeypatch.delenv("POC_METRICS_TOKEN", raising=False)
    with TestClient(app, base_url="https://mcp.example.com") as client:
        assert client.get("/metrics").status_code == 404


def test_metrics_endpoint_requires_the_configured_token(app, monkeypatch):
    monkeypatch.setenv("POC_METRICS_TOKEN", "scrape-token-123")
    with TestClient(app, base_url="https://mcp.example.com") as client:
        before = count("mcp_http_requests_total", route="/healthz", method="GET", status="2xx")
        client.get("/healthz")
        client.post("/mcp", json={})
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
        scraped = client.get("/metrics", headers={"Authorization": "Bearer scrape-token-123"})
    assert scraped.status_code == 200
    assert scraped.headers["content-type"].startswith("text/plain")
    assert count("mcp_http_requests_total", route="/healthz", method="GET", status="2xx") == before + 1
    assert 'mcp_http_requests_total{method="POST",route="/mcp",status="4xx"}' in scraped.text
    assert "scrape-token-123" not in scraped.text


def test_tool_outcomes_are_counted(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED_FEATURES", "common")
    upstream = Mock()
    upstream.get_record.return_value = {"sys_id": ID, "number": "INC0001"}
    server = create_server(lambda: upstream)
    labels = dict(tool="get_record")
    ok = count("mcp_tool_calls_total", **labels, outcome="success", error_code="none")
    bad = count("mcp_tool_calls_total", **labels, outcome="error", error_code="VALIDATION_ERROR")
    unknown = count("mcp_tool_calls_total", tool="unknown", outcome="error", error_code="UNKNOWN_TOOL")

    async def run():
        async with Client(server, mode="legacy") as client:
            await client.call_tool("get_record", {"table": "incident", "sys_id": ID})
            await client.call_tool("get_record", {"table": "sys_user", "sys_id": ID}, raise_on_error=False)
            with pytest.raises(Exception):
                await client.call_tool("no_such_tool", {})

    asyncio.run(run())
    assert count("mcp_tool_calls_total", **labels, outcome="success", error_code="none") == ok + 1
    assert count("mcp_tool_calls_total", **labels, outcome="error", error_code="VALIDATION_ERROR") == bad + 1
    assert count("mcp_tool_calls_total", tool="unknown", outcome="error", error_code="UNKNOWN_TOOL") == unknown + 1


@pytest.mark.parametrize("outcome,label", [(200, "2xx"), (403, "403"), (429, "429"), (503, "5xx"),
                                           (requests.ConnectionError(), "no_response")])
def test_servicenow_responses_are_counted(outcome, label):
    client = ServiceNowClient(Settings("example.test", oauth_access_token="token"))
    if isinstance(outcome, Exception):
        client.session.request = Mock(side_effect=outcome)
    else:
        client.session.request = Mock(return_value=Mock(status_code=outcome, json=Mock(return_value={"result": []})))
    before = count("servicenow_responses_total", status=label)
    try:
        client.list_records("incident", limit=1)
    except Exception:
        pass
    assert count("servicenow_responses_total", status=label) == before + 1


@pytest.mark.parametrize("respond,result", [
    (lambda r: httpx2.Response(200, json={"result": {"sys_id": ID, "user_name": "a"}}), "valid"),
    (lambda r: httpx2.Response(401), "rejected"),
    (lambda r: httpx2.Response(503), "servicenow_unavailable"),
    (lambda r: (_ for _ in ()).throw(httpx2.ConnectError("down")), "servicenow_unavailable"),
])
def test_identity_checks_are_counted(settings, respond, result):
    before = count("servicenow_identity_checks_total", result=result)

    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
            await ServiceNowTokenVerifier(settings, http).verify_token("sn-token")

    asyncio.run(run())
    assert count("servicenow_identity_checks_total", result=result) == before + 1
