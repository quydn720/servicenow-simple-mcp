"""ServiceNow upstream validation; never install this verifier standalone."""

import re

import httpx2
from fastmcp.server.auth import AccessToken, OAuthProxy, TokenVerifier
from fastmcp.server.dependencies import get_access_token

from servicenow_mcp.config.local import Settings
from servicenow_mcp.config.remote import RemoteSettings
from servicenow_mcp.client import ServiceNowClient
from servicenow_mcp.errors import OperationError
from servicenow_mcp.observability.metrics import record_identity_check


class ServiceNowTokenVerifier(TokenVerifier):
    """Validate only broker-obtained upstream tokens against the current user API.

    No identity or role cache: disabled users/revoked tokens fail closed on the
    next request. ACLs remain ServiceNow's responsibility on every Table API call.
    """

    def __init__(self, settings: RemoteSettings, http_client=None):
        super().__init__(required_scopes=[])
        self.settings = settings
        self.http_client = http_client

    async def verify_token(self, token: str) -> AccessToken | None:
        outcome = {"result": "rejected"}

        async def verify(client):
            response = await client.get(
                self.settings.instance + self.settings.identity_path,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                follow_redirects=False,
                timeout=15,
            )
            if response.status_code >= 500 or response.status_code == 429:
                outcome["result"] = "servicenow_unavailable"
            if response.status_code != 200:
                return None
            user = response.json().get("result")
            if not isinstance(user, dict):
                return None
            subject = user.get("sys_id")
            if not isinstance(subject, str) or not re.fullmatch(
                r"[0-9a-f]{32}", subject
            ):
                return None
            return AccessToken(
                token=token,
                client_id=self.settings.client_id,
                scopes=[],
                subject=subject,
                claims={
                    "sub": subject,
                    "servicenow_instance": self.settings.instance,
                    "provider": "servicenow",
                    "user_name": user.get("user_name", ""),
                },
            )

        try:
            if self.http_client is not None:
                verified = await verify(self.http_client)
            else:
                async with httpx2.AsyncClient() as client:
                    verified = await verify(client)
        except httpx2.HTTPError:
            record_identity_check("servicenow_unavailable")
            return None
        except (ValueError, TypeError, AttributeError):
            record_identity_check("rejected")
            return None
        record_identity_check("valid" if verified is not None else outcome["result"])
        return verified


class ReadOnlyServiceNowClient(ServiceNowClient):
    def _request(self, method, path, params=None, json_body=None, display_fields=()):
        if method != "GET" or not re.fullmatch(
            r"/table/(incident|task|sc_task|problem|change_request|kb_knowledge)(/[0-9a-f]{32})?",
            path,
        ):
            raise OperationError("PERMISSION_DENIED")
        return super()._request(method, path, params, json_body, display_fields)


def user_client_factory(settings: RemoteSettings):
    def current_client():
        token = get_access_token()
        if (
            token is None
            or not token.token
            or not token.subject
            or token.claims.get("provider") != "servicenow"
            or token.claims.get("servicenow_instance") != settings.instance
        ):
            raise OperationError("AUTHENTICATION_REQUIRED")
        # Explicit settings: shared .env credentials can never be used as fallback.
        return ReadOnlyServiceNowClient(
            Settings(
                instance=settings.instance,
                auth_type="oauth",
                oauth_access_token=token.token,
            )
        )

    return current_client


def create_auth(settings: RemoteSettings, storage, http_client=None):
    return OAuthProxy(
        upstream_authorization_endpoint=settings.instance + "/oauth_auth.do",
        upstream_token_endpoint=settings.instance + "/oauth_token.do",
        upstream_client_id=settings.client_id,
        upstream_client_secret=settings.client_secret,
        token_verifier=ServiceNowTokenVerifier(settings, http_client),
        base_url=settings.public_url,
        redirect_path="/auth/callback",
        allowed_client_redirect_uris=list(settings.allowed_redirects),
        client_storage=storage,
        jwt_signing_key=settings.signing_key,
        token_endpoint_auth_method="client_secret_post",
        forward_pkce=settings.forward_pkce,
        forward_resource=False,
        # Clients get no ServiceNow scopes to choose from; the broker always
        # requests the configured one so instance auth scopes can restrict it.
        extra_authorize_params={"scope": settings.servicenow_scope} if settings.servicenow_scope else None,
        valid_scopes=[],
        require_authorization_consent=True,
        # ServiceNow returns expires_in, so its Access Token Lifespan applies;
        # this is used only if a response ever omits it.
        fallback_access_token_expiry_seconds=300,
        # ServiceNow omits refresh_expires_in, so this sets the sign-in length.
        fallback_refresh_token_expiry_seconds=settings.session_lifetime_seconds,
        token_expiry_threshold_seconds=30,
        enable_cimd=True,
    )
