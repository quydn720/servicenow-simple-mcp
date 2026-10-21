"""Load and latency test for the remote MCP server.

Local mode (default) runs the real broker app in-process against a simulated
ServiceNow with configurable latency, signs in through the full OAuth flow,
then sends concurrent tools/call requests:

    uv run --locked --extra remote python loadtest/run.py
    uv run --locked --extra remote python loadtest/run.py --servicenow-ms 300 --levels 1,20,80

Remote mode measures a deployed server with an MCP access token obtained by
signing in with any OAuth-capable MCP client:

    MCP_LOADTEST_TOKEN=... uv run --locked --extra remote python loadtest/run.py \
        --url https://mcp.example.com/mcp --levels 1,10 --requests 100

Only read tools are called. Do not point remote mode at production without the
service owner's approval: every request reaches ServiceNow as the token's user.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import parse_qs, urlparse

import httpx2

CALLBACK = "http://127.0.0.1:8766/callback"
TOOL_CALL = {"name": "list_incidents", "arguments": {"number": "INC0010001"}}


def percentile(values, pct):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))]


def rpc_body(request_id):
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {**TOOL_CALL, "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {}}}}


def rpc_headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2026-07-28", "MCP-Method": "tools/call",
            "MCP-Name": TOOL_CALL["name"]}


async def run_level(client, url, token, concurrency, total):
    latencies, errors = [], 0
    gate = asyncio.Semaphore(concurrency)

    async def one(i):
        nonlocal errors
        async with gate:
            start = time.perf_counter()
            try:
                response = await client.post(url, headers=rpc_headers(token), json=rpc_body(i), timeout=60)
                ok = response.status_code == 200 and not response.json().get("result", {}).get("isError")
            except (httpx2.HTTPError, ValueError):
                ok = False
            latencies.append(time.perf_counter() - start)
            errors += not ok

    start = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(total)))
    wall = time.perf_counter() - start
    return {"concurrency": concurrency, "requests": total, "errors": errors,
            "p50_ms": percentile(latencies, 50) * 1000, "p95_ms": percentile(latencies, 95) * 1000,
            "p99_ms": percentile(latencies, 99) * 1000, "throughput_rps": total / wall}


def local_app(servicenow_seconds):
    """The real broker app wired to a simulated ServiceNow."""
    import requests
    from cryptography.fernet import Fernet
    from fastmcp.server.auth.oauth_proxy import proxy
    from key_value.aio.stores.memory import MemoryStore

    from servicenow_mcp.config.remote import RemoteSettings
    from servicenow_mcp.servers.remote import create_remote_server

    user_id = "a" * 32

    async def servicenow(request):  # token endpoint and identity API
        await asyncio.sleep(servicenow_seconds)
        if request.url.path == "/oauth_token.do":
            return httpx2.Response(200, json={"access_token": "sn-user", "refresh_token": "sn-refresh",
                                              "expires_in": 1800, "token_type": "Bearer"})
        return httpx2.Response(200, json={"result": {"sys_id": user_id, "user_name": "load.test"}})

    transport = httpx2.MockTransport(servicenow)
    original = proxy.AsyncOAuth2Client

    def oauth_client(*args, **kwargs):
        result = original(*args, **kwargs)
        result._client = httpx2.AsyncClient(transport=transport)
        return result

    proxy.AsyncOAuth2Client = oauth_client

    def table_api(session, **kwargs):  # runs in the tool's worker thread
        time.sleep(servicenow_seconds)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"result": [{
            "number": "INC0010001", "short_description": "Printer problem",
            "state": {"value": "2", "display_value": "In Progress"},
            "priority": {"value": "3", "display_value": "3 - Moderate"},
            "sys_updated_on": "2026-10-19 08:00:00"}]}).encode()
        return response

    requests.Session.request = table_api
    settings = RemoteSettings(
        "https://instance.example.com", "https://mcp.example.com", "loadtest-app", "loadtest-secret",
        "s" * 64, Fernet.generate_key().decode(), (CALLBACK,), forward_pkce=False,
        allow_dynamic_registration=True)
    server = create_remote_server(settings, storage=MemoryStore(),
                                  http_client=httpx2.AsyncClient(transport=transport))
    return server.http_app(path="/mcp", stateless_http=True, json_response=True,
                           host_origin_protection=True, allowed_hosts=["mcp.example.com"],
                           allowed_origins=[settings.public_url])


async def sign_in(client):
    """Full OAuth flow against the broker; returns (token, step timings in ms)."""
    timings = {}

    async def timed(step, coro):
        start = time.perf_counter()
        response = await coro
        timings[step] = (time.perf_counter() - start) * 1000
        return response

    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    registered = await timed("register", client.post("/register", json={
        "client_name": "Load test", "redirect_uris": [CALLBACK],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "none"}))
    client_id = registered.json()["client_id"]
    authorize = await timed("authorize", client.get("/authorize", params={
        "client_id": client_id, "redirect_uri": CALLBACK, "response_type": "code", "state": "s",
        "code_challenge": challenge, "code_challenge_method": "S256",
        "resource": "https://mcp.example.com/mcp"}))
    consent = await client.get(authorize.headers["location"])
    form = {k: re.search(fr'name="{k}" value="([^"]+)"', consent.text)[1] for k in ("txn_id", "csrf_token")}
    approved = await timed("consent", client.post("/consent", data={**form, "action": "approve"}))
    state = parse_qs(urlparse(approved.headers["location"]).query)["state"][0]
    callback = await timed("callback", client.get("/auth/callback", params={"state": state, "code": "x"}))
    code = parse_qs(urlparse(callback.headers["location"]).query)["code"][0]
    token = await timed("token", client.post("/token", data={
        "grant_type": "authorization_code", "client_id": client_id, "redirect_uri": CALLBACK,
        "code": code, "code_verifier": verifier, "resource": "https://mcp.example.com/mcp"}))
    return token.json()["access_token"], timings


async def main(args):
    levels = [int(x) for x in args.levels.split(",")]
    if args.url:
        token = os.environ.get("MCP_LOADTEST_TOKEN", "")
        if not token:
            sys.exit("Set MCP_LOADTEST_TOKEN to an MCP access token for --url mode.")
        async with httpx2.AsyncClient(limits=httpx2.Limits(max_connections=max(levels))) as client:
            results = [await run_level(client, args.url, token, level, args.requests) for level in levels]
        timings = {}
    else:
        app = local_app(args.servicenow_ms / 1000)
        # ASGITransport skips app startup, which the MCP session manager needs.
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                          base_url="https://mcp.example.com",
                                          follow_redirects=False) as client:
                token, timings = await sign_in(client)
                results = [await run_level(client, "/mcp", token, level, args.requests)
                           for level in levels]
    report = {"mode": "remote" if args.url else "local", "servicenow_ms": None if args.url else args.servicenow_ms,
              "sign_in_ms": {k: round(v, 1) for k, v in timings.items()},
              "levels": [{k: round(v, 1) if isinstance(v, float) else v for k, v in r.items()} for r in results]}
    if args.json:
        print(json.dumps(report))
        return
    if timings:
        print("Sign-in steps (ms): " + ", ".join(f"{k} {v:.0f}" for k, v in timings.items()))
    print(f"{'concurrency':>11} {'requests':>8} {'errors':>6} {'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8} {'req/s':>7}")
    for r in results:
        print(f"{r['concurrency']:>11} {r['requests']:>8} {r['errors']:>6} {r['p50_ms']:>8.0f} "
              f"{r['p95_ms']:>8.0f} {r['p99_ms']:>8.0f} {r['throughput_rps']:>7.1f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="Deployed /mcp URL (remote mode); omit for local mode")
    parser.add_argument("--servicenow-ms", type=int, default=200, help="Simulated ServiceNow latency per call")
    parser.add_argument("--levels", default="1,10,40,80", help="Comma-separated concurrency levels")
    parser.add_argument("--requests", type=int, default=400, help="Requests per level")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    asyncio.run(main(parser.parse_args()))
