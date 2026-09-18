import requests
from requests.auth import HTTPBasicAuth
from app.config import Settings


class BasicAuthProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def authenticate(self, session: requests.Session) -> None:
        session.headers.pop("Authorization", None)
        session.auth = HTTPBasicAuth(self.settings.username, self.settings.password)
