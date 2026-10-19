"""Structured, redacted logs with a request ID on every line.

Logs go to stdout as one JSON object per line (POC_LOG_FORMAT=json, the
default) or plain text (POC_LOG_FORMAT=text), so any log platform can collect
them. Secrets are removed before anything is written: bearer tokens, OAuth
codes and state, token and secret fields, and URL query strings.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone

REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_SENSITIVE = r"access_token|refresh_token|id_token|client_secret|client_assertion|code_verifier|password|code|state|token|assertion"
_REDACTIONS = [
    # URL query strings can carry codes and state; keep the path only.
    (re.compile(r"(https?://[^\s?#\"'<>]+)\?[^\s\"'<>]*"), r"\1?[REDACTED]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"), r"\1 [REDACTED]"),
    (re.compile(rf"(?i)\b({_SENSITIVE})=([^&\s\"',;]+)"), r"\1=[REDACTED]"),
    (re.compile(rf"(?i)([\"']({_SENSITIVE})[\"']\s*:\s*[\"'])[^\"']*"), r"\1[REDACTED]"),
    # FastMCP's OAuth proxy logs these values in plain sentences.
    (re.compile(r"(?i)\b(authorization code(?: not found| expired)?:?\s+)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(transaction(?:\s+id)?:?\s+)[A-Za-z0-9_-]{8,}"), r"\1[REDACTED]"),
]
_REQUEST_ID_FORMAT = re.compile(r"[A-Za-z0-9._-]{8,64}")
# Structured fields copied from log records; each is built from safe values.
_STRUCTURED_FIELDS = ("http",)
_QUIET_LOGGERS = ("httpx", "httpx2", "httpcore", "authlib")
# Its DEBUG lines carry full authorization codes; never go below INFO.
_OAUTH_LOGGER = "fastmcp.server.auth"

logger = logging.getLogger("servicenow_mcp.http")


def redact(text: str) -> str:
    """Remove secrets from free text."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        request_id = REQUEST_ID.get()
        if request_id:
            entry["request_id"] = request_id
        for name in _STRUCTURED_FIELDS:
            if isinstance(getattr(record, name, None), dict):
                entry[name] = getattr(record, name)
        audits = {k: v for k, v in vars(record).items() if k.endswith("_audit") and isinstance(v, dict)}
        if audits:
            entry["audit"] = next(iter(audits.values())) if len(audits) == 1 else audits
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, default=str)


class RedactingTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        request_id = REQUEST_ID.get()
        prefix = f"[{request_id}] " if request_id else ""
        return redact(prefix + super().format(record))


def configure_logging() -> None:
    """Send all logs, including FastMCP's and uvicorn's, through one redacting handler."""
    level = os.getenv("POC_LOG_LEVEL", "INFO").strip().upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ValueError("POC_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
    log_format = os.getenv("POC_LOG_FORMAT", "json").strip().lower()
    if log_format not in ("json", "text"):
        raise ValueError("POC_LOG_FORMAT must be json or text")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if log_format == "json"
        else RedactingTextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("fastmcp", "mcp", "uvicorn", "uvicorn.error", "uvicorn.access"):
        named = logging.getLogger(name)
        named.handlers.clear()
        named.propagate = True
        named.setLevel(logging.NOTSET)
    # HTTP clients log full URLs, including OAuth query strings, at INFO.
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(logging.WARNING, root.level))
    logging.getLogger(_OAUTH_LOGGER).setLevel(max(logging.INFO, root.level))


class RequestContextMiddleware:
    """Assign a request ID, echo it as X-Request-ID, and log one safe line per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _REQUEST_ID_FORMAT.fullmatch(incoming) else uuid.uuid4().hex
        token = REQUEST_ID.set(request_id)
        started = time.perf_counter()
        status = {"code": 500}

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                headers = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            # The path never includes the query string, which can carry OAuth codes.
            logger.info(
                "%s %s %s", scope.get("method"), scope.get("path"), status["code"],
                extra={"http": {
                    "method": scope.get("method"), "path": scope.get("path"),
                    "status": status["code"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }},
            )
            REQUEST_ID.reset(token)
