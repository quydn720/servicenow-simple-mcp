import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    instance: str
    oauth_client_id: str
    oauth_client_secret: str
    oauth_refresh_token: str = ""
    oauth_access_token: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        instance = os.getenv("SERVICENOW_INSTANCE", "").strip().rstrip("/")
        oauth_client_id = os.getenv("SERVICENOW_OAUTH_CLIENT_ID", "").strip()
        oauth_client_secret = os.getenv("SERVICENOW_OAUTH_CLIENT_SECRET", "").strip()
        oauth_refresh_token = os.getenv("SERVICENOW_OAUTH_REFRESH_TOKEN", "").strip()
        oauth_access_token = os.getenv("SERVICENOW_OAUTH_ACCESS_TOKEN", "").strip()

        if not instance:
            raise RuntimeError("Missing SERVICENOW_INSTANCE environment variable")
        if not oauth_client_id:
            raise RuntimeError("Missing SERVICENOW_OAUTH_CLIENT_ID environment variable")
        if not oauth_client_secret:
            raise RuntimeError("Missing SERVICENOW_OAUTH_CLIENT_SECRET environment variable")
        if not oauth_refresh_token and not oauth_access_token:
            raise RuntimeError(
                "Set SERVICENOW_OAUTH_REFRESH_TOKEN or "
                "SERVICENOW_OAUTH_ACCESS_TOKEN"
            )

        return cls(
            instance=instance,
            oauth_client_id=oauth_client_id,
            oauth_client_secret=oauth_client_secret,
            oauth_refresh_token=oauth_refresh_token,
            oauth_access_token=oauth_access_token,
        )
