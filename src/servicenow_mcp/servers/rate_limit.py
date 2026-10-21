"""Per-caller request rate limits for the remote server.

Limits live in this process, which matches the single-replica deployment;
shared token storage (a later item) would also need shared counters.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections import OrderedDict

from servicenow_mcp.observability.metrics import REGISTRY

# Browser routes come from users' own addresses; Claude's registration and
# token calls, and all /mcp traffic, come from shared Anthropic addresses.
GROUPS = {
    "/mcp": "mcp",
    "/authorize": "sign_in",
    "/consent": "sign_in",
    "/auth/callback": "sign_in",
    "/register": "oauth_api",
    "/token": "oauth_api",
    "/revoke": "oauth_api",
}
DEFAULTS = {"mcp": 120, "sign_in": 30, "oauth_api": 300}
ENV = {
    "mcp": "POC_RATE_LIMIT_MCP_PER_MINUTE",
    "sign_in": "POC_RATE_LIMIT_SIGN_IN_PER_MINUTE",
    "oauth_api": "POC_RATE_LIMIT_OAUTH_API_PER_MINUTE",
}
MAX_TRACKED_CALLERS = 10_000


def limits_from_env() -> dict[str, int]:
    limits = {}
    for group, name in ENV.items():
        value = os.getenv(name, str(DEFAULTS[group])).strip()
        if not value.isdigit() or not 1 <= int(value) <= 100_000:
            raise ValueError(f"{name} must be a whole number from 1 to 100000")
        limits[group] = int(value)
    return limits


class TokenBuckets:
    """One bucket per (group, caller): `limit` requests, refilled over a minute."""

    def __init__(self, limits: dict[str, int], clock=time.monotonic):
        self.limits = limits
        self.clock = clock
        self.buckets: OrderedDict[tuple[str, str], tuple[float, float]] = OrderedDict()

    def take(self, group: str, caller: str) -> float:
        """Return 0 if allowed, else seconds until the next request is allowed."""
        limit = self.limits[group]
        rate = limit / 60.0
        now = self.clock()
        key = (group, caller)
        tokens, updated = self.buckets.pop(key, (float(limit), now))
        tokens = min(float(limit), tokens + (now - updated) * rate)
        if tokens >= 1:
            self.buckets[key] = (tokens - 1, now)
            allowed = 0.0
        else:
            self.buckets[key] = (tokens, now)
            allowed = (1 - tokens) / rate
        while len(self.buckets) > MAX_TRACKED_CALLERS:
            self.buckets.popitem(last=False)
        return allowed


def caller_key(scope, group: str) -> str:
    """Never store raw tokens or full addresses as keys longer than needed."""
    if group == "mcp":
        auth = dict(scope.get("headers") or []).get(b"authorization", b"")
        if auth:
            return "token:" + hashlib.sha256(auth).hexdigest()[:32]
    client = scope.get("client")
    return "ip:" + (client[0] if client else "unknown")


class RateLimitMiddleware:
    def __init__(self, app, limits: dict[str, int] | None = None, clock=time.monotonic):
        self.app = app
        self.buckets = TokenBuckets(limits or limits_from_env(), clock)

    async def __call__(self, scope, receive, send):
        group = GROUPS.get(scope.get("path", "")) if scope["type"] == "http" else None
        if group is None:
            await self.app(scope, receive, send)
            return
        wait = self.buckets.take(group, caller_key(scope, group))
        if not wait:
            await self.app(scope, receive, send)
            return
        REGISTRY.inc("mcp_rate_limited_total", group=group)
        retry_after = str(max(1, math.ceil(wait)))
        body = json.dumps({"error": "rate_limited",
                           "error_description": "Too many requests; retry later."}).encode()
        await send({"type": "http.response.start", "status": 429, "headers": [
            (b"content-type", b"application/json"), (b"retry-after", retry_after.encode()),
            (b"cache-control", b"no-store"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
