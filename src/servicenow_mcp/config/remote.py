"""Configuration for the isolated, read-only remote authorization POC."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet


def https_origin(value: str, name: str) -> str:
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise ValueError(f"{name} must be an HTTPS origin without a path or credentials")
    return value.rstrip("/")


@dataclass(frozen=True)
class RemoteSettings:
    instance: str
    public_url: str
    client_id: str
    client_secret: str = field(repr=False)
    signing_key: str = field(repr=False)
    encryption_key: str = field(repr=False)
    allowed_redirects: tuple[str, ...]
    identity_path: str = "/api/x_mcp_poc/identity/me"
    storage_dir: Path = Path(".oauth-poc")
    # This broker is a confidential upstream client. Some ServiceNow releases
    # interpret a PKCE challenge as public-client mode and reject client_secret.
    forward_pkce: bool = False

    def __post_init__(self):
        object.__setattr__(self, "instance", https_origin(self.instance, "POC_SERVICENOW_INSTANCE"))
        object.__setattr__(self, "public_url", https_origin(self.public_url, "POC_PUBLIC_URL"))
        if not self.client_id.strip() or not self.client_secret.strip():
            raise ValueError("POC OAuth client ID and secret are required")
        if len(self.signing_key) < 32:
            raise ValueError("POC_SIGNING_KEY must contain at least 32 random characters")
        try:
            Fernet(self.encryption_key.encode())
        except (ValueError, TypeError):
            raise ValueError("POC_ENCRYPTION_KEY must be a Fernet key") from None
        if not self.allowed_redirects:
            raise ValueError("POC_ALLOWED_REDIRECT_URIS must list approved client callbacks")
        for uri in self.allowed_redirects:
            parsed = urlparse(uri)
            loopback = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
            if (not parsed.hostname or parsed.username or parsed.password or parsed.fragment
                    or "*" in uri or (parsed.scheme != "https" and not loopback)):
                raise ValueError("Client callbacks must be exact HTTPS or loopback HTTP URLs; no wildcards")
        if (not self.identity_path.startswith("/api/") or ".." in self.identity_path
                or any(c in self.identity_path for c in "?#\\")):
            raise ValueError("POC_IDENTITY_PATH must be an absolute ServiceNow API path")

    @classmethod
    def from_env(cls):
        def required(name):
            value = os.getenv(name, "").strip()
            if not value:
                raise ValueError(f"Missing configuration: {name}")
            return value

        pkce = os.getenv("POC_FORWARD_PKCE", "false").lower()
        if pkce not in ("true", "false"):
            raise ValueError("POC_FORWARD_PKCE must be true or false")
        return cls(
            instance=required("POC_SERVICENOW_INSTANCE"),
            public_url=required("POC_PUBLIC_URL"),
            client_id=required("POC_SERVICENOW_CLIENT_ID"),
            client_secret=required("POC_SERVICENOW_CLIENT_SECRET"),
            signing_key=required("POC_SIGNING_KEY"),
            encryption_key=required("POC_ENCRYPTION_KEY"),
            allowed_redirects=tuple(uri.strip() for uri in required("POC_ALLOWED_REDIRECT_URIS").split(",") if uri.strip()),
            identity_path=os.getenv("POC_IDENTITY_PATH", "/api/x_mcp_poc/identity/me"),
            storage_dir=Path(os.getenv("POC_STORAGE_DIR", ".oauth-poc")),
            forward_pkce=pkce == "true",
        )
