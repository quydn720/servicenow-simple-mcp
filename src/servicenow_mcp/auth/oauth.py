import requests
from servicenow_mcp.config.local import Settings
from servicenow_mcp.errors import OperationError


class OAuthProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def authenticate(self, session: requests.Session) -> None:
        settings = self.settings
        token = settings.oauth_access_token
        if settings.oauth_refresh_token:
            instance = settings.instance.rstrip("/")
            if "://" not in instance:
                instance = "https://" + instance
            try:
                response = requests.post(
                    f"{instance}/oauth_token.do",
                    data={
                        "grant_type": "refresh_token",
                        "client_id": settings.oauth_client_id,
                        "client_secret": settings.oauth_client_secret,
                        "refresh_token": settings.oauth_refresh_token,
                    },
                    headers={"Accept": "application/json"},
                    timeout=30,
                )
            except requests.Timeout:
                raise OperationError("TIMEOUT", retryable=True) from None
            except requests.RequestException:
                raise OperationError("UPSTREAM_ERROR", retryable=True) from None
            if response.status_code >= 400:
                raise OperationError(
                    "AUTHENTICATION_REQUIRED"
                    if response.status_code < 500 and response.status_code != 429
                    else "UPSTREAM_ERROR",
                    retryable=response.status_code >= 500
                    or response.status_code == 429,
                    http_status=response.status_code,
                )
            try:
                data = response.json()
            except ValueError:
                raise OperationError("UPSTREAM_ERROR") from None
            token = data.get("access_token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise OperationError("AUTHENTICATION_REQUIRED")
        session.auth = None
        session.headers["Authorization"] = f"Bearer {token}"
