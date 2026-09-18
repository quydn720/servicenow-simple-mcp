import os
from dataclasses import dataclass, field

DEFAULT_FEATURES = ("common", "service_desk", "product_owner")
KNOWN_FEATURES = (*DEFAULT_FEATURES, "developer")


def enabled_features() -> tuple[str, ...]:
    raw = os.getenv("MCP_ENABLED_FEATURES", ",".join(DEFAULT_FEATURES))
    features = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    if not features:
        raise RuntimeError("MCP_ENABLED_FEATURES must contain at least one feature")
    if set(features) - set(KNOWN_FEATURES):
        raise RuntimeError("Unknown MCP_ENABLED_FEATURES; expected: " + ", ".join(KNOWN_FEATURES))
    return features


@dataclass(frozen=True)
class Settings:
    instance: str
    oauth_client_id: str = ""
    oauth_client_secret: str = field(default="", repr=False)
    oauth_refresh_token: str = field(default="", repr=False)
    oauth_access_token: str = field(default="", repr=False)
    auth_type: str = "oauth"
    username: str = ""
    password: str = field(default="", repr=False)

    def validate(self) -> None:
        if self.auth_type not in ("basic", "oauth"):
            raise RuntimeError("SERVICENOW_AUTH_TYPE must be basic or oauth")
        required = {"SERVICENOW_INSTANCE": self.instance}
        if self.auth_type == "basic":
            required.update(SERVICENOW_USERNAME=self.username, SERVICENOW_PASSWORD=self.password)
        elif self.oauth_refresh_token:
            required.update(SERVICENOW_OAUTH_CLIENT_ID=self.oauth_client_id,
                            SERVICENOW_OAUTH_CLIENT_SECRET=self.oauth_client_secret)
        elif not self.oauth_access_token:
            raise RuntimeError("Set SERVICENOW_OAUTH_REFRESH_TOKEN or SERVICENOW_OAUTH_ACCESS_TOKEN")
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError("Missing configuration: " + ", ".join(missing))

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            instance=os.getenv("SERVICENOW_INSTANCE", "").strip().rstrip("/"),
            auth_type=os.getenv("SERVICENOW_AUTH_TYPE", "oauth").strip().lower(),
            username=os.getenv("SERVICENOW_USERNAME", "").strip(),
            password=os.getenv("SERVICENOW_PASSWORD", ""),
            oauth_client_id=os.getenv("SERVICENOW_OAUTH_CLIENT_ID", "").strip(),
            oauth_client_secret=os.getenv("SERVICENOW_OAUTH_CLIENT_SECRET", "").strip(),
            oauth_refresh_token=os.getenv("SERVICENOW_OAUTH_REFRESH_TOKEN", "").strip(),
            oauth_access_token=os.getenv("SERVICENOW_OAUTH_ACCESS_TOKEN", "").strip(),
        )
        settings.validate()
        return settings
