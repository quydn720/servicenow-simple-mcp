import asyncio
import base64
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from cryptography.fernet import Fernet
from key_value.aio.stores.memory import MemoryStore
from starlette.testclient import TestClient

from servicenow_mcp.auth.servicenow_remote import ServiceNowTokenVerifier, user_client_factory
from servicenow_mcp.config.remote import RemoteSettings
from servicenow_mcp.servers.remote import create_remote_server, encrypted_storage

USER_A = "a" * 32
USER_B = "b" * 32
CALLBACK = "http://127.0.0.1:8766/callback"


@pytest.fixture
def settings(tmp_path, request):
    return RemoteSettings(
        "https://instance.example.com", "https://mcp.example.com", "poc-app",
        "upstream-secret", "s" * 64, Fernet.generate_key().decode(), (CALLBACK,),
        storage_dir=tmp_path / "tokens", forward_pkce=getattr(request, "param", True),
    )


def challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


class Upstream:
    """Mock ServiceNow's token and identity endpoints, with revocation support."""
    def __init__(self, expect_pkce=True):
        self.revoked = set()
        self.requests = []
        self.expect_pkce = expect_pkce

    def __call__(self, request):
        self.requests.append(request)
        if request.url.path == "/oauth_token.do":
            params = parse_qs(request.content.decode())
            assert params["client_id"] == ["poc-app"]
            assert params["client_secret"] == ["upstream-secret"]
            if params["grant_type"] == ["authorization_code"]:
                user = params["code"][0]
                assert params["redirect_uri"] == ["https://mcp.example.com/auth/callback"]
                if self.expect_pkce:
                    assert len(params["code_verifier"][0]) >= 43
                else:
                    assert "code_verifier" not in params
            else:
                assert params["grant_type"] == ["refresh_token"]
                user = params["refresh_token"][0].removeprefix("refresh-")
            if user in self.revoked:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            return httpx2.Response(200, json={"access_token": "sn-" + user,
                "refresh_token": "refresh-" + user, "expires_in": 3600,
                "refresh_expires_in": 86400, "token_type": "Bearer"})
        assert request.url.path == "/api/x_mcp_poc/identity/me"
        user = request.headers["authorization"].removeprefix("Bearer sn-")
        if user not in ("A", "B") or user in self.revoked:
            return httpx2.Response(401)
        return httpx2.Response(200, json={"result": {
            "sys_id": USER_A if user == "A" else USER_B, "user_name": user,
        }})


@pytest.fixture
def remote(settings, monkeypatch):
    from fastmcp.server.auth.oauth_proxy import proxy
    upstream = Upstream(expect_pkce=settings.forward_pkce)
    transport = httpx2.MockTransport(upstream)
    original = proxy.AsyncOAuth2Client

    def oauth_client(*args, **kwargs):
        result = original(*args, **kwargs)
        result._client = httpx2.AsyncClient(transport=transport)
        return result

    monkeypatch.setattr(proxy, "AsyncOAuth2Client", oauth_client)
    verifier_client = httpx2.AsyncClient(transport=transport)
    server = create_remote_server(settings, storage=MemoryStore(), http_client=verifier_client)
    app = server.http_app(path="/mcp", stateless_http=True, json_response=True,
        host_origin_protection=True, allowed_hosts=["mcp.example.com"],
        allowed_origins=[settings.public_url])
    with TestClient(app, base_url=settings.public_url, follow_redirects=False) as client:
        yield client, server, upstream
    asyncio.run(verifier_client.aclose())


def authorize(client, user, *, verifier="v" * 64, forward_pkce=True):
    registered = client.post("/register", json={"client_name": "Test " + user,
        "redirect_uris": [CALLBACK], "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "token_endpoint_auth_method": "none"})
    assert registered.status_code == 201, registered.text
    client_id = registered.json()["client_id"]
    auth = client.get("/authorize", params={"client_id": client_id, "redirect_uri": CALLBACK,
        "response_type": "code", "state": "client-state", "code_challenge": challenge(verifier),
        "code_challenge_method": "S256", "resource": "https://mcp.example.com/mcp"})
    assert auth.status_code == 302, auth.text
    consent = client.get(auth.headers["location"])
    assert consent.status_code == 200
    form = {key: re.search(fr'name="{key}" value="([^"]+)"', consent.text)[1]
            for key in ("txn_id", "csrf_token")}
    approved = client.post("/consent", data={**form, "action": "approve"})
    assert approved.status_code == 302, approved.text
    upstream_params = parse_qs(urlparse(approved.headers["location"]).query)
    assert "resource" not in upstream_params
    if forward_pkce:
        assert upstream_params["code_challenge_method"] == ["S256"]
    else:
        assert "code_challenge" not in upstream_params
        assert "code_challenge_method" not in upstream_params
    callback = client.get("/auth/callback", params={"state": upstream_params["state"][0], "code": user})
    assert callback.status_code == 302, re.sub("<[^>]+>", "", callback.text)[-800:]
    params = parse_qs(urlparse(callback.headers["location"]).query)
    assert params["state"] == ["client-state"]
    return {"grant_type": "authorization_code", "client_id": client_id,
            "redirect_uri": CALLBACK, "code": params["code"][0], "code_verifier": verifier,
            "resource": "https://mcp.example.com/mcp"}


def login(client, user, *, forward_pkce=True):
    form = authorize(client, user, forward_pkce=forward_pkce)
    response = client.post("/token", data=form)
    assert response.status_code == 200, response.text
    assert "sn-" + user not in response.text
    assert "refresh-" + user not in response.text
    return response.json(), form


def rpc(client, token, method, params=None):
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2026-07-28",
               "MCP-Method": method}
    if method == "tools/call":
        headers["MCP-Name"] = params["name"]
    return client.post("/mcp", headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method,
              "params": {**(params or {}), "_meta": {
                  "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                  "io.modelcontextprotocol/clientCapabilities": {},
              }}})


def test_discovery_and_unauthenticated_requests(remote):
    client, _, _ = remote
    denied = client.post("/mcp", json={})
    assert denied.status_code == 401
    assert "resource_metadata=" in denied.headers["www-authenticate"]
    resource = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert resource["resource"] == "https://mcp.example.com/mcp"
    metadata = client.get("/.well-known/oauth-authorization-server").json()
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert metadata["client_id_metadata_document_supported"] is True
    assert rpc(client, "sn-A", "tools/list").status_code == 401
    assert client.get("/auth/callback", params={"state": "forged", "code": "A"}).status_code == 400
    rejected = client.post("/register", json={"redirect_uris": ["https://evil.example/callback"]})
    assert rejected.status_code >= 400


@pytest.mark.parametrize("settings", [False], indirect=True)
def test_confidential_upstream_keeps_client_pkce(remote):
    client, _, _ = remote
    form = authorize(client, "A", forward_pkce=False)
    assert client.post("/token", data={**form, "code_verifier": "incorrect" * 8}).status_code >= 400
    tokens, _ = login(client, "A", forward_pkce=False)
    assert rpc(client, tokens["access_token"], "tools/list").status_code == 200


def test_legacy_protocol_client_and_host_origin_guards(remote):
    client, _, _ = remote
    tokens, _ = login(client, "A")
    headers = {"Authorization": "Bearer " + tokens["access_token"],
               "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
    initialized = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1,
        "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "legacy-test", "version": "1"}}})
    assert initialized.status_code == 200, initialized.text
    tools = client.post("/mcp", headers=headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert tools.status_code == 200, tools.text
    assert {t["name"] for t in tools.json()["result"]["tools"]} == {"list_records", "get_record"}
    for extra in ({"Host": "evil.example"}, {"Origin": "https://evil.example"}):
        rejected = client.post("/mcp", headers={**headers, **extra}, json={})
        assert rejected.status_code in (403, 421)


def test_consent_cookie_binding_and_missing_pkce(remote):
    client, _, _ = remote
    form = authorize(client, "A")
    missing = client.get("/authorize", params={"client_id": form["client_id"],
        "redirect_uri": CALLBACK, "response_type": "code", "state": "test"})
    if missing.status_code == 302:
        redirected = urlparse(missing.headers["location"])
        assert redirected.hostname == "127.0.0.1"
        assert parse_qs(redirected.query)["error"] == ["invalid_request"]
    else:
        assert missing.status_code >= 400
    # A separate browser cannot submit an authorization prepared elsewhere.
    auth = client.get("/authorize", params={"client_id": form["client_id"], "redirect_uri": CALLBACK,
        "response_type": "code", "state": "state", "code_challenge": challenge("v" * 64),
        "code_challenge_method": "S256"})
    consent = client.get(auth.headers["location"])
    fields = {key: re.search(fr'name="{key}" value="([^"]+)"', consent.text)[1]
              for key in ("txn_id", "csrf_token")}
    client.cookies.clear()
    assert client.post("/consent", data={**fields, "action": "approve"}).status_code == 403


def test_persistent_grant_and_transparent_refresh(remote, settings):
    client, server, upstream = remote
    tokens, _ = login(client, "A")
    auth = server.auth
    payload = auth.jwt_issuer.verify_token(tokens["access_token"])

    async def run():
        mapping = await auth._jti_mapping_store.get(payload["jti"])
        stored = await auth._upstream_token_store.get(mapping.upstream_token_id)
        stored.expires_at = 0
        await auth._upstream_token_store.put(mapping.upstream_token_id, stored, ttl=3600)
        verified = await auth.load_access_token(tokens["access_token"])
        assert verified.subject == USER_A
        assert verified.token == "sn-A"
    asyncio.run(run())
    assert any(b"grant_type=refresh_token" in r.content for r in upstream.requests)

    # Recreate the provider over the same store and key, as after a restart.
    recreated = create_remote_server(settings, storage=auth._client_storage,
                                    http_client=auth._token_validator.http_client)
    recreated.http_app(path="/mcp", stateless_http=True)
    restored = asyncio.run(recreated.auth.load_access_token(tokens["access_token"]))
    assert restored.subject == USER_A and restored.token == "sn-A"


def test_pkce_replay_and_wrong_audience(remote):
    client, server, _ = remote
    form = authorize(client, "A")
    bad = client.post("/token", data={**form, "code_verifier": "wrong" * 16})
    assert bad.status_code >= 400
    # A failed verifier need not preserve the code; use a new flow.
    tokens, form = login(client, "A")
    assert client.post("/token", data=form).status_code >= 400
    assert rpc(client, tokens["access_token"] + "tampered", "tools/list").status_code == 401
    # Correctly signed token with an audience for another MCP must be rejected.
    from fastmcp.server.auth.jwt_issuer import JWTIssuer
    issuer = JWTIssuer(issuer="https://mcp.example.com/", audience="https://other.example/mcp",
                       signing_key=server.auth._jwt_signing_key)
    foreign = issuer.issue_access_token(client_id=form["client_id"], scopes=[], jti="other", expires_in=60)
    assert rpc(client, foreign, "tools/list").status_code == 401


def test_remote_raw_query_rejected_before_servicenow_request(remote, monkeypatch):
    import requests
    from unittest.mock import Mock

    client, _, _ = remote
    tokens, _ = login(client, "A")
    request = Mock(side_effect=AssertionError("Unexpected ServiceNow request"))
    monkeypatch.setattr(requests.Session, "request", request)
    result = rpc(client, tokens["access_token"], "tools/call", {
        "name": "list_records",
        "arguments": {"table": "incident", "query": "active=true"},
    })
    assert result.status_code == 200, result.text
    assert result.json()["result"]["isError"] is True
    assert "RAW_QUERY_PROHIBITED" in str(result.json()["result"]["content"])
    request.assert_not_called()


def test_two_users_concurrent_reads_acl_errors_and_revocation(remote, monkeypatch):
    import requests
    client, _, upstream = remote
    tokens_a, _ = login(client, "A")
    tokens_b, _ = login(client, "B")
    seen = []

    def request(session, **kwargs):
        token = session.headers["Authorization"]
        seen.append(token)
        response = requests.Response()
        response.status_code = 403 if kwargs["url"].endswith("/" + "c" * 32) else 200
        response._content = (b'{"result":[{"number":"HR-A"}]}' if token == "Bearer sn-A"
                             else b'{"result":[{"number":"IT-B"}]}')
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    monkeypatch.setenv("SERVICENOW_OAUTH_ACCESS_TOKEN", "shared-admin-token")
    tools = rpc(client, tokens_a["access_token"], "tools/list")
    assert tools.status_code == 200, tools.text
    assert {t["name"] for t in tools.json()["result"]["tools"]} == {"list_records", "get_record"}
    def read(token):
        result = rpc(client, token, "tools/call", {"name": "list_records", "arguments": {"table": "incident"}})
        assert result.status_code == 200, result.text
        return result.json()["result"]
    with ThreadPoolExecutor(2) as pool:
        a, b = list(pool.map(read, [tokens_a["access_token"], tokens_b["access_token"]]))
    assert "HR-A" in str(a) and "IT-B" not in str(a)
    assert "IT-B" in str(b) and "HR-A" not in str(b)
    assert set(seen) == {"Bearer sn-A", "Bearer sn-B"}
    denied = rpc(client, tokens_a["access_token"], "tools/call", {
        "name": "get_record", "arguments": {"table": "incident", "sys_id": "c" * 32}})
    assert denied.json()["result"]["isError"] is True
    upstream.revoked.add("A")
    assert rpc(client, tokens_a["access_token"], "tools/list").status_code == 401
    assert rpc(client, tokens_b["access_token"], "tools/list").status_code == 200


def test_refresh_is_client_bound(remote):
    client, _, upstream = remote
    tokens_a, form_a = login(client, "A")
    _, form_b = login(client, "B")
    form = {"grant_type": "refresh_token", "client_id": form_b["client_id"],
            "refresh_token": tokens_a["refresh_token"], "resource": "https://mcp.example.com/mcp"}
    assert client.post("/token", data=form).status_code >= 400
    refreshed = client.post("/token", data={**form, "client_id": form_a["client_id"]})
    assert refreshed.status_code == 200, refreshed.text
    assert rpc(client, refreshed.json()["access_token"], "tools/list").status_code == 200
    assert any(b"grant_type=refresh_token" in r.content for r in upstream.requests)


@pytest.mark.parametrize("response", [httpx2.Response(401), httpx2.Response(403),
    httpx2.Response(302, headers={"Location": "https://evil.example"}),
    httpx2.Response(200, text="not JSON"), httpx2.Response(200, json={"result": {"sys_id": "guest"}})])
def test_verifier_fails_closed(settings, response):
    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _: response)) as client:
            assert await ServiceNowTokenVerifier(settings, client).verify_token("invalid") is None
    asyncio.run(run())


def test_no_shared_fallback_or_write_access(settings, monkeypatch):
    from fastmcp.server.auth import AccessToken
    import servicenow_mcp.auth.servicenow_remote as module
    factory = user_client_factory(settings)
    monkeypatch.setattr(module, "get_access_token", lambda: None)
    with pytest.raises(RuntimeError):
        factory()
    token = AccessToken(token="sn-A", client_id="poc-app", scopes=[], subject=USER_A,
                        claims={"provider": "servicenow", "servicenow_instance": settings.instance})
    monkeypatch.setattr(module, "get_access_token", lambda: token)
    client = factory()
    assert client.session.headers["Authorization"] == "Bearer sn-A"
    for operation in (lambda: client.create_record("incident", {}),
                      lambda: client.get_record("incident", "../../sys_user")):
        with pytest.raises(ValueError):
            operation()


def test_encrypted_storage_survives_restart(settings):
    async def run():
        first = encrypted_storage(settings)
        await first.put("token-record", {"access_token": "secret-upstream-token"})
        second = encrypted_storage(settings)
        assert await second.get("token-record") == {"access_token": "secret-upstream-token"}
    asyncio.run(run())
    for path in settings.storage_dir.rglob("*"):
        if path.is_file():
            assert b"secret-upstream-token" not in path.read_bytes()


@pytest.mark.parametrize("changes", [{"instance": "http://instance.example.com"},
    {"public_url": "https://mcp.example.com/mcp"}, {"allowed_redirects": ()},
    {"allowed_redirects": ("https://*.example.com/callback",)}, {"signing_key": "short"},
    {"identity_path": "https://evil.example/me"}])
def test_invalid_configuration(settings, changes):
    with pytest.raises(ValueError):
        replace(settings, **changes)
