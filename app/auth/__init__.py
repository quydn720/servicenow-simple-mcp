from typing import Protocol
import requests


class AuthProvider(Protocol):
    def authenticate(self, session: requests.Session) -> None: ...
