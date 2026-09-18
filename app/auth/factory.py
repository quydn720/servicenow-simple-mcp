from app.auth import AuthProvider
from app.auth.basic import BasicAuthProvider
from app.auth.oauth import OAuthProvider
from app.config import Settings


def create_auth_provider(settings: Settings) -> AuthProvider:
    settings.validate()
    if settings.auth_type == "basic":
        return BasicAuthProvider(settings)
    return OAuthProvider(settings)
