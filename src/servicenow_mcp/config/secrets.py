"""Read secret settings from the environment or from mounted secret files.

Every secret setting NAME may instead be given as NAME_FILE, a path to a file
holding the value. Secret managers (Kubernetes and Docker secrets, cloud
secret-store drivers) can mount secrets as files, which keeps them out of the
process environment. Setting both is an error, so the source is never ambiguous.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from servicenow_mcp.config.environment import environment_file

SECRET_SETTINGS = (
    "MCP_SERVICENOW_CLIENT_SECRET",
    "MCP_SIGNING_KEY",
    "MCP_ENCRYPTION_KEY",
    "MCP_METRICS_TOKEN",
)


def read_secret(name: str, *, required: bool = True) -> str:
    value = os.getenv(name, "").strip()
    path = os.getenv(f"{name}_FILE", "").strip()
    if value and path:
        raise ValueError(f"Set {name} or {name}_FILE, not both")
    if path:
        try:
            text = Path(path).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            raise ValueError(f"{name}_FILE could not be read") from None
        if not text:
            raise ValueError(f"{name}_FILE is empty")
        return text
    if required and not value:
        raise ValueError(f"Missing configuration: {name} (or {name}_FILE)")
    return value


def secret_source(name: str) -> str:
    """Where a secret comes from: "file", "dotenv" (plain text in the
    .env.remote file), "environment" (injected by the platform) or "absent"."""
    if os.getenv(f"{name}_FILE", "").strip():
        return "file"
    if not os.getenv(name, "").strip():
        return "absent"
    try:
        written = (dotenv_values(environment_file(remote=True)).get(name) or "").strip()
    except OSError:
        written = ""
    return "dotenv" if written else "environment"


def split_keys(value: str) -> list[str]:
    """A comma-separated list of keys, newest first."""
    return [part.strip() for part in value.split(",") if part.strip()]
