"""Configuration for the isolated, read-only remote authorization POC."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet

from servicenow_mcp.config.secrets import read_secret, split_keys

# Claude's client ID metadata document (CIMD) URL.
CLAUDE_CLIENT_ID = "https://claude.ai/oauth/mcp-oauth-client-metadata"
SESSION_LIFETIME_MIN = 3600  # 1 hour
SESSION_LIFETIME_MAX = 30 * 86400  # 30 days


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
    # ServiceNow returns no refresh-token expiry, so this caps how long a client
    # sign-in lasts before the user must sign in again.
    session_lifetime_seconds: int = 86400
    # OAuth scope requested from ServiceNow at sign-in. Pair it with REST API
    # auth scopes on the instance so tokens can only call the APIs this needs.
    servicenow_scope: str = ""
    # MCP clients allowed to sign in, by their client ID metadata URL.
    approved_clients: tuple[str, ...] = (CLAUDE_CLIENT_ID,)
    # Open /register lets any client register; off unless explicitly needed.
    allow_dynamic_registration: bool = False

    def __post_init__(self):
        object.__setattr__(self, "instance", https_origin(self.instance, "POC_SERVICENOW_INSTANCE"))
        object.__setattr__(self, "public_url", https_origin(self.public_url, "POC_PUBLIC_URL"))
        if not self.client_id.strip() or not self.client_secret.strip():
            raise ValueError("POC OAuth client ID and secret are required")
        if len(self.signing_key) < 32:
            raise ValueError("POC_SIGNING_KEY must contain at least 32 random characters")
        keys = split_keys(self.encryption_key)
        if not keys:
            raise ValueError("POC_ENCRYPTION_KEY must hold at least one Fernet key")
        for key in keys:
            try:
                Fernet(key.encode())
            except (ValueError, TypeError):
                raise ValueError("POC_ENCRYPTION_KEY must be Fernet keys, newest first, comma-separated") from None
        if not self.allowed_redirects:
            raise ValueError("POC_ALLOWED_REDIRECT_URIS must list approved client callbacks")
        for uri in self.allowed_redirects:
            parsed = urlparse(uri)
            loopback = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
            if (not parsed.hostname or parsed.username or parsed.password or parsed.fragment
                    or "*" in uri or (parsed.scheme != "https" and not loopback)):
                raise ValueError("Client callbacks must be exact HTTPS or loopback HTTP URLs; no wildcards")
        if not SESSION_LIFETIME_MIN <= self.session_lifetime_seconds <= SESSION_LIFETIME_MAX:
            raise ValueError(
                f"POC_SESSION_LIFETIME_SECONDS must be {SESSION_LIFETIME_MIN}-{SESSION_LIFETIME_MAX}"
            )
        if self.servicenow_scope and not re.fullmatch(
            r"[A-Za-z0-9_.:-]+( [A-Za-z0-9_.:-]+)*", self.servicenow_scope
        ) or len(self.servicenow_scope) > 200:
            raise ValueError("POC_SERVICENOW_SCOPE must be space-separated scope names")
        for client in self.approved_clients:
            parsed = urlparse(client)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.path in ("", "/")
                    or parsed.query or parsed.fragment or "*" in client):
                raise ValueError("POC_APPROVED_CLIENTS must be exact HTTPS client metadata URLs")
        if not self.approved_clients and not self.allow_dynamic_registration:
            raise ValueError("Approve at least one client or allow dynamic registration")
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

        lifetime = os.getenv("POC_SESSION_LIFETIME_SECONDS", "86400").strip()
        if not lifetime.isdigit():
            raise ValueError("POC_SESSION_LIFETIME_SECONDS must be a whole number of seconds")
        registration = os.getenv("POC_ALLOW_DYNAMIC_REGISTRATION", "false").strip().lower()
        if registration not in ("true", "false"):
            raise ValueError("POC_ALLOW_DYNAMIC_REGISTRATION must be true or false")
        approved = os.getenv("POC_APPROVED_CLIENTS")
        approved_clients = (CLAUDE_CLIENT_ID,) if approved is None else tuple(
            item.strip() for item in approved.split(",") if item.strip())
        pkce = os.getenv("POC_FORWARD_PKCE", "false").lower()
        if pkce not in ("true", "false"):
            raise ValueError("POC_FORWARD_PKCE must be true or false")
        return cls(
            instance=required("POC_SERVICENOW_INSTANCE"),
            public_url=required("POC_PUBLIC_URL"),
            client_id=required("POC_SERVICENOW_CLIENT_ID"),
            client_secret=read_secret("POC_SERVICENOW_CLIENT_SECRET"),
            signing_key=read_secret("POC_SIGNING_KEY"),
            encryption_key=read_secret("POC_ENCRYPTION_KEY"),
            allowed_redirects=tuple(uri.strip() for uri in required("POC_ALLOWED_REDIRECT_URIS").split(",") if uri.strip()),
            identity_path=os.getenv("POC_IDENTITY_PATH", "/api/x_mcp_poc/identity/me"),
            storage_dir=Path(os.getenv("POC_STORAGE_DIR", ".oauth-poc")),
            forward_pkce=pkce == "true",
            session_lifetime_seconds=int(lifetime),
            servicenow_scope=" ".join(os.getenv("POC_SERVICENOW_SCOPE", "").split()),
            approved_clients=approved_clients,
            allow_dynamic_registration=registration == "true",
        )
