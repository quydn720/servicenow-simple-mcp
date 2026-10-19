"""Per-caller rate limits on the remote server's routes."""

import pytest
from cryptography.fernet import Fernet
from key_value.aio.stores.memory import MemoryStore
from starlette.middleware import Middleware
from starlette.testclient import TestClient

from servicenow_mcp.config.remote import RemoteSettings
from servicenow_mcp.observability.logs import RequestContextMiddleware
from servicenow_mcp.observability.metrics import REGISTRY
from servicenow_mcp.servers import rate_limit
from servicenow_mcp.servers.rate_limit import (
    RateLimitMiddleware, TokenBuckets, caller_key, limits_from_env,
)
from servicenow_mcp.servers.remote import create_remote_server


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_bucket_allows_the_limit_then_refills_over_a_minute():
    clock = Clock()
    buckets = TokenBuckets({"sign_in": 3}, clock)
    assert [buckets.take("sign_in", "ip:a") for _ in range(3)] == [0, 0, 0]
    wait = buckets.take("sign_in", "ip:a")
    assert wait == pytest.approx(20.0)  # 3 per minute: one every 20 s
    assert buckets.take("sign_in", "ip:b") == 0  # other callers are separate
    clock.now += 20
    assert buckets.take("sign_in", "ip:a") == 0
    assert buckets.take("sign_in", "ip:a") > 0


def test_tracked_callers_are_bounded(monkeypatch):
    monkeypatch.setattr(rate_limit, "MAX_TRACKED_CALLERS", 5)
    buckets = TokenBuckets({"sign_in": 1}, Clock())
    for i in range(20):
        buckets.take("sign_in", f"ip:{i}")
    assert len(buckets.buckets) == 5


def test_mcp_callers_are_keyed_by_a_token_hash_and_others_by_address():
    scope = {"headers": [(b"authorization", b"Bearer secret-mcp-token")], "client": ("10.0.0.7", 5000)}
    key = caller_key(scope, "mcp")
    assert key.startswith("token:") and "secret-mcp-token" not in key
    assert caller_key(scope, "sign_in") == "ip:10.0.0.7"
    assert caller_key({"headers": [], "client": ("10.0.0.7", 1)}, "mcp") == "ip:10.0.0.7"


def test_limits_from_env(monkeypatch):
    for name in rate_limit.ENV.values():
        monkeypatch.delenv(name, raising=False)
    assert limits_from_env() == {"mcp": 120, "sign_in": 30, "oauth_api": 300}
    monkeypatch.setenv("POC_RATE_LIMIT_SIGN_IN_PER_MINUTE", "5")
    assert limits_from_env()["sign_in"] == 5


@pytest.mark.parametrize("value", ["0", "-1", "ten", "100001"])
def test_invalid_limits_are_rejected(monkeypatch, value):
    monkeypatch.setenv("POC_RATE_LIMIT_MCP_PER_MINUTE", value)
    with pytest.raises(ValueError):
        limits_from_env()


@pytest.fixture
def client(tmp_path):
    settings = RemoteSettings(
        "https://instance.example.com", "https://mcp.example.com", "poc-app", "upstream-secret",
        "s" * 64, Fernet.generate_key().decode(), ("http://127.0.0.1:8766/callback",),
        storage_dir=tmp_path / "tokens")
    server = create_remote_server(settings, storage=MemoryStore())
    app = server.http_app(
        path="/mcp", stateless_http=True, json_response=True, host_origin_protection=True,
        allowed_hosts=["mcp.example.com"], allowed_origins=[settings.public_url],
        middleware=[Middleware(RequestContextMiddleware),
                    Middleware(RateLimitMiddleware, limits={"mcp": 2, "sign_in": 2, "oauth_api": 2})])
    with TestClient(app, base_url="https://mcp.example.com", follow_redirects=False) as test_client:
        yield test_client


def test_sign_in_routes_return_429_with_retry_after(client):
    before = REGISTRY._counters.get(("mcp_rate_limited_total", (("group", "sign_in"),)), 0)
    statuses = [client.get("/authorize").status_code for _ in range(3)]
    assert statuses[:2] != [429, 429] and statuses[2] == 429
    refused = client.get("/consent")  # same group, same caller
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) >= 1
    assert refused.json()["error"] == "rate_limited"
    assert refused.headers["x-request-id"]  # still traced and logged
    assert REGISTRY._counters[("mcp_rate_limited_total", (("group", "sign_in"),))] >= before + 2


def test_each_sign_in_has_its_own_mcp_limit(client):
    first = {"Authorization": "Bearer token-one"}
    second = {"Authorization": "Bearer token-two"}
    assert [client.post("/mcp", headers=first, json={}).status_code for _ in range(3)][-1] == 429
    assert client.post("/mcp", headers=second, json={}).status_code != 429


def test_health_metrics_and_discovery_are_never_limited(client):
    for _ in range(5):
        assert client.get("/healthz").status_code == 200
        assert client.get("/.well-known/oauth-authorization-server").status_code == 200
        assert client.get("/metrics").status_code != 429
