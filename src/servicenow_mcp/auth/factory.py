from servicenow_mcp.auth import AuthProvider
from servicenow_mcp.auth.basic import BasicAuthProvider
from servicenow_mcp.auth.oauth import OAuthProvider
from servicenow_mcp.config.local import Settings


def create_auth_provider(settings: Settings) -> AuthProvider:
    settings.validate()
    if settings.auth_type == "basic":
        return BasicAuthProvider(settings)
    return OAuthProvider(settings)
