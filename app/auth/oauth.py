import requests
from app.config import Settings


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
                    data={"grant_type": "refresh_token",
                          "client_id": settings.oauth_client_id,
                          "client_secret": settings.oauth_client_secret,
                          "refresh_token": settings.oauth_refresh_token},
                    headers={"Accept": "application/json"}, timeout=30,
                )
            except requests.RequestException:
                raise RuntimeError("ServiceNow OAuth token request failed; check connectivity") from None
            if response.status_code >= 400:
                raise RuntimeError(f"ServiceNow OAuth token request failed (HTTP {response.status_code})")
            try:
                data = response.json()
            except ValueError:
                raise RuntimeError("ServiceNow OAuth token response was not JSON") from None
            token = data.get("access_token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise RuntimeError("ServiceNow OAuth response did not include an access_token")
        session.auth = None
        session.headers["Authorization"] = f"Bearer {token}"
