"""Small, thread-safe Prometheus-format metrics for the remote server.

Only bounded label values are recorded (known routes, tool names, status
classes, error codes), never request values, users, or record identifiers.
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from collections import defaultdict

from starlette.responses import PlainTextResponse, Response

DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
KNOWN_ROUTES = frozenset({
    "/mcp", "/healthz", "/metrics", "/authorize", "/token", "/register", "/consent",
    "/revoke", "/auth/callback", "/.well-known/oauth-protected-resource/mcp",
    "/.well-known/oauth-authorization-server",
})
UPSTREAM_STATUSES = frozenset({401, 403, 404, 408, 429})

_HELP = {
    "mcp_http_requests_total": ("counter", "HTTP requests by route, method and status class."),
    "mcp_http_request_duration_seconds": ("histogram", "HTTP request duration by route."),
    "mcp_tool_calls_total": ("counter", "MCP tool calls by tool, outcome and error code."),
    "servicenow_responses_total": ("counter", "ServiceNow API responses by status."),
    "servicenow_identity_checks_total": ("counter", "Sign-in token checks against ServiceNow by result."),
    "mcp_process_start_time_seconds": ("gauge", "Unix time the server process started."),
}


class Registry:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[tuple, float] = defaultdict(float)
        self._histograms: dict[tuple, list] = {}
        self.started = time.time()

    def inc(self, name: str, **labels: str) -> None:
        with self._lock:
            self._counters[(name, tuple(sorted(labels.items())))] += 1

    def observe(self, name: str, seconds: float, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            buckets = self._histograms.setdefault(key, [0] * len(DURATION_BUCKETS) + [0, 0.0])
            for i, bound in enumerate(DURATION_BUCKETS):
                if seconds <= bound:
                    buckets[i] += 1
            buckets[-2] += 1
            buckets[-1] += seconds

    def render(self) -> str:
        def fmt(labels):
            return "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}" if labels else ""

        with self._lock:
            counters = dict(self._counters)
            histograms = {k: list(v) for k, v in self._histograms.items()}
        lines, seen = [], set()

        def header(name):
            if name not in seen:
                seen.add(name)
                kind, text = _HELP[name]
                lines.extend([f"# HELP {name} {text}", f"# TYPE {name} {kind}"])

        header("mcp_process_start_time_seconds")
        lines.append(f"mcp_process_start_time_seconds {self.started:.0f}")
        for (name, labels), value in sorted(counters.items()):
            header(name)
            lines.append(f"{name}{fmt(labels)} {value:g}")
        for (name, labels), data in sorted(histograms.items()):
            header(name)
            for bound, count in zip(DURATION_BUCKETS, data):
                lines.append(f"{name}_bucket{fmt(labels + (('le', str(bound)),))} {count}")
            lines.append(f"{name}_bucket{fmt(labels + (('le', '+Inf'),))} {data[-2]}")
            lines.append(f"{name}_count{fmt(labels)} {data[-2]}")
            lines.append(f"{name}_sum{fmt(labels)} {data[-1]:.6f}")
        return "\n".join(lines) + "\n"


REGISTRY = Registry()


def route_label(path: str) -> str:
    return path if path in KNOWN_ROUTES else "other"


def record_request(method: str, path: str, status: int, seconds: float) -> None:
    route = route_label(path)
    REGISTRY.inc("mcp_http_requests_total", route=route, method=method or "-", status=f"{status // 100}xx")
    REGISTRY.observe("mcp_http_request_duration_seconds", seconds, route=route)


def record_tool_call(tool: str, outcome: str, error_code: str = "") -> None:
    REGISTRY.inc("mcp_tool_calls_total", tool=tool, outcome=outcome, error_code=error_code or "none")


def record_servicenow_response(status: int | None) -> None:
    """status None means no HTTP response (timeout or connection failure)."""
    if status is None:
        label = "no_response"
    elif status in UPSTREAM_STATUSES:
        label = str(status)
    else:
        label = f"{status // 100}xx"
    REGISTRY.inc("servicenow_responses_total", status=label)


def record_identity_check(result: str) -> None:
    REGISTRY.inc("servicenow_identity_checks_total", result=result)


async def metrics_endpoint(request) -> Response:
    """Serve metrics only to a caller with POC_METRICS_TOKEN; hidden otherwise."""
    expected = os.getenv("POC_METRICS_TOKEN", "")
    if not expected:
        return Response(status_code=404)
    supplied = request.headers.get("authorization", "")
    if not hmac.compare_digest(supplied.encode(), f"Bearer {expected}".encode()):
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    return PlainTextResponse(REGISTRY.render(), media_type="text/plain; version=0.0.4",
                             headers={"Cache-Control": "no-store"})
