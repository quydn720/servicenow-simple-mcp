"""Configuration for the read-only remote server (the Claude connector)."""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet

from servicenow_mcp.config.secrets import SECRET_SETTINGS, read_secret, secret_source, split_keys

logger = logging.getLogger(__name__)

ENVIRONMENTS = ("development", "test", "production")
ENFORCED_ENVIRONMENTS = ("test", "production")
TUNNEL_HOSTS = (".ngrok-free.app", ".ngrok-free.dev", ".ngrok.io", ".ngrok.app", ".trycloudflare.com")

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
    identity_path: str = "/api/x_mcp/identity/me"
    storage_dir: Path = Path(".mcp-tokens")
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
    # ServiceNow token revocation endpoint; empty skips the ServiceNow call
    # (the local grant is still deleted).
    revoke_path: str = "/oauth_revoke_token.do"
    # Deployment environment; test and production enforce the policy below.
    environment: str = "development"
    # Where each secret came from (never the value); see secret_source().
    secret_sources: dict = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "instance", https_origin(self.instance, "MCP_SERVICENOW_INSTANCE"))
        object.__setattr__(self, "public_url", https_origin(self.public_url, "MCP_PUBLIC_URL"))
        if not self.client_id.strip() or not self.client_secret.strip():
            raise ValueError("MCP_SERVICENOW_CLIENT_ID and MCP_SERVICENOW_CLIENT_SECRET are required")
        if len(self.signing_key) < 32:
            raise ValueError("MCP_SIGNING_KEY must contain at least 32 random characters")
        keys = split_keys(self.encryption_key)
        if not keys:
            raise ValueError("MCP_ENCRYPTION_KEY must hold at least one Fernet key")
        for key in keys:
            try:
                Fernet(key.encode())
            except (ValueError, TypeError):
                raise ValueError("MCP_ENCRYPTION_KEY must be Fernet keys, newest first, comma-separated") from None
        if not self.allowed_redirects:
            raise ValueError("MCP_ALLOWED_REDIRECT_URIS must list approved client callbacks")
        for uri in self.allowed_redirects:
            parsed = urlparse(uri)
            loopback = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
            if (not parsed.hostname or parsed.username or parsed.password or parsed.fragment
                    or "*" in uri or (parsed.scheme != "https" and not loopback)):
                raise ValueError("Client callbacks must be exact HTTPS or loopback HTTP URLs; no wildcards")
        if not SESSION_LIFETIME_MIN <= self.session_lifetime_seconds <= SESSION_LIFETIME_MAX:
            raise ValueError(
                f"MCP_SESSION_LIFETIME_SECONDS must be {SESSION_LIFETIME_MIN}-{SESSION_LIFETIME_MAX}"
            )
        if self.servicenow_scope and not re.fullmatch(
            r"[A-Za-z0-9_.:-]+( [A-Za-z0-9_.:-]+)*", self.servicenow_scope
        ) or len(self.servicenow_scope) > 200:
            raise ValueError("MCP_SERVICENOW_SCOPE must be space-separated scope names")
        for client in self.approved_clients:
            parsed = urlparse(client)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.path in ("", "/")
                    or parsed.query or parsed.fragment or "*" in client):
                raise ValueError("MCP_APPROVED_CLIENTS must be exact HTTPS client metadata URLs")
        if not self.approved_clients and not self.allow_dynamic_registration:
            raise ValueError("Approve at least one client or allow dynamic registration")
        if self.revoke_path and (not self.revoke_path.startswith("/") or ".." in self.revoke_path
                                 or any(c in self.revoke_path for c in "?#\\ ")):
            raise ValueError("MCP_SERVICENOW_REVOKE_PATH must be an absolute ServiceNow path")
        if self.environment not in ENVIRONMENTS:
            raise ValueError("MCP_ENVIRONMENT must be development, test or production")
        if (not self.identity_path.startswith("/api/") or ".." in self.identity_path
                or any(c in self.identity_path for c in "?#\\")):
            raise ValueError("MCP_IDENTITY_PATH must be an absolute ServiceNow API path")

    def policy_violations(self) -> list[str]:
        """Settings not acceptable outside development (see docs/servicenow-access.md)."""
        problems = [
            f"{name} is plain text in the .env.remote file; provide {name}_FILE or inject it from a secret store"
            for name, source in sorted(self.secret_sources.items()) if source == "dotenv"
        ]
        if not self.servicenow_scope:
            problems.append("MCP_SERVICENOW_SCOPE must be set so ServiceNow tokens reach only the APIs the broker needs")
        if self.allow_dynamic_registration:
            problems.append("MCP_ALLOW_DYNAMIC_REGISTRATION must be false")
        if not self.revoke_path:
            problems.append("MCP_SERVICENOW_REVOKE_PATH must be set so /revoke ends ServiceNow grants")
        host = (urlparse(self.public_url).hostname or "").lower()
        if self.environment == "production" and host.endswith(TUNNEL_HOSTS):
            problems.append("MCP_PUBLIC_URL must be the production domain, not a tunnel host")
        return problems

    def enforce_environment_policy(self) -> None:
        problems = self.policy_violations()
        if not problems:
            return
        if self.environment in ENFORCED_ENVIRONMENTS:
            raise ValueError(f"Settings not allowed in {self.environment}: " + "; ".join(problems))
        for problem in problems:
            logger.warning("Not allowed outside development: %s", problem)

    @classmethod
    def from_env(cls):
        def required(name):
            value = os.getenv(name, "").strip()
            if not value:
                raise ValueError(f"Missing configuration: {name}")
            return value

        lifetime = os.getenv("MCP_SESSION_LIFETIME_SECONDS", "86400").strip()
        if not lifetime.isdigit():
            raise ValueError("MCP_SESSION_LIFETIME_SECONDS must be a whole number of seconds")
        registration = os.getenv("MCP_ALLOW_DYNAMIC_REGISTRATION", "false").strip().lower()
        if registration not in ("true", "false"):
            raise ValueError("MCP_ALLOW_DYNAMIC_REGISTRATION must be true or false")
        approved = os.getenv("MCP_APPROVED_CLIENTS")
        approved_clients = (CLAUDE_CLIENT_ID,) if approved is None else tuple(
            item.strip() for item in approved.split(",") if item.strip())
        environment = os.getenv("MCP_ENVIRONMENT", "development").strip().lower()
        pkce = os.getenv("MCP_FORWARD_PKCE", "false").lower()
        if pkce not in ("true", "false"):
            raise ValueError("MCP_FORWARD_PKCE must be true or false")
        settings = cls(
            instance=required("MCP_SERVICENOW_INSTANCE"),
            public_url=required("MCP_PUBLIC_URL"),
            client_id=required("MCP_SERVICENOW_CLIENT_ID"),
            client_secret=read_secret("MCP_SERVICENOW_CLIENT_SECRET"),
            signing_key=read_secret("MCP_SIGNING_KEY"),
            encryption_key=read_secret("MCP_ENCRYPTION_KEY"),
            allowed_redirects=tuple(uri.strip() for uri in required("MCP_ALLOWED_REDIRECT_URIS").split(",") if uri.strip()),
            # The Scripted REST namespace differs per instance; no default.
            identity_path=required("MCP_IDENTITY_PATH"),
            storage_dir=Path(os.getenv("MCP_STORAGE_DIR", ".mcp-tokens")),
            forward_pkce=pkce == "true",
            session_lifetime_seconds=int(lifetime),
            servicenow_scope=" ".join(os.getenv("MCP_SERVICENOW_SCOPE", "").split()),
            approved_clients=approved_clients,
            allow_dynamic_registration=registration == "true",
            revoke_path=os.getenv("MCP_SERVICENOW_REVOKE_PATH", "/oauth_revoke_token.do").strip(),
            environment=environment,
            secret_sources={name: secret_source(name) for name in SECRET_SETTINGS
                            if secret_source(name) != "absent"},
        )
        settings.enforce_environment_policy()
        return settings
