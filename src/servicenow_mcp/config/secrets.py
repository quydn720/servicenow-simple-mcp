"""Read secret settings from the environment or from mounted secret files.

Every secret setting NAME may instead be given as NAME_FILE, a path to a file
holding the value. Secret managers (Kubernetes and Docker secrets, cloud
secret-store drivers) can mount secrets as files, which keeps them out of the
process environment. Setting both is an error, so the source is never ambiguous.
"""

from __future__ import annotations

import os
from pathlib import Path

SECRET_SETTINGS = (
    "POC_SERVICENOW_CLIENT_SECRET",
    "POC_SIGNING_KEY",
    "POC_ENCRYPTION_KEY",
    "POC_METRICS_TOKEN",
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


def split_keys(value: str) -> list[str]:
    """A comma-separated list of keys, newest first."""
    return [part.strip() for part in value.split(",") if part.strip()]
