"""ServiceNow upstream validation; never install this verifier standalone."""

import logging
import re

import httpx2
from fastmcp.server.auth import AccessToken, OAuthProxy, TokenVerifier
from mcp.server.auth.settings import RevocationOptions
from fastmcp.server.dependencies import get_access_token

from servicenow_mcp.config.local import Settings
from servicenow_mcp.config.remote import RemoteSettings
from servicenow_mcp.client import ServiceNowClient
from servicenow_mcp.errors import OperationError
from servicenow_mcp.observability.metrics import record_identity_check, record_revocation

logger = logging.getLogger(__name__)


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


class ServiceNowOAuthProxy(OAuthProxy):
    """FastMCP's OAuth proxy with client approval and real revocation.

    Approval: clients identify themselves by a client ID metadata URL (Claude
    does) or, only when enabled, by dynamic registration. Lookups run for
    /authorize, /token and refresh, so removing a client from the list also
    ends its existing sign-ins. Unapproved metadata URLs are never fetched.

    Revocation: /revoke (RFC 7009) revokes the ServiceNow tokens behind the
    MCP token and deletes the stored grant, so the MCP access and refresh
    tokens stop working at once. FastMCP's own upstream revocation would send
    the MCP token, which ServiceNow does not know, and leave access tokens
    valid until they expire.
    """

    def __init__(self, *, approved_clients, allow_dynamic_registration,
                 servicenow_revoke_url="", revocation_http_client=None, **kwargs):
        super().__init__(**kwargs)
        self._approved_clients = frozenset(approved_clients)
        self._allow_dynamic_registration = allow_dynamic_registration
        if self.client_registration_options is not None:
            self.client_registration_options.enabled = allow_dynamic_registration
        self._servicenow_revoke_url = servicenow_revoke_url
        self._revocation_http_client = revocation_http_client
        self.revocation_options = RevocationOptions(enabled=True)

    async def load_access_token(self, token: str):
        loaded = await super().load_access_token(token)
        if loaded is None:
            return None
        # The verifier labels tokens with the ServiceNow app's client ID and
        # carries the ServiceNow token (tools call ServiceNow with it). Record
        # the MCP client and the broker grant ID too: the revocation handler
        # only revokes a token belonging to the calling client, and
        # revoke_token needs the grant ID to find what to revoke.
        try:
            payload = self.jwt_issuer.verify_token(token)
        except Exception:
            return loaded
        update = {"claims": {**loaded.claims, "mcp_jti": payload.get("jti")}}
        if payload.get("client_id"):
            update["client_id"] = payload["client_id"]
        return loaded.model_copy(update=update)

    async def revoke_token(self, token) -> None:
        upstream = None
        try:
            # An access token loaded above carries its grant ID in claims; a
            # refresh token is the broker-signed token itself.
            jti = (getattr(token, "claims", None) or {}).get("mcp_jti")
            if not jti:
                jti = self.jwt_issuer.verify_token(token.token, expected_token_use="refresh")["jti"]
            mapping = await self._jti_mapping_store.get(key=jti)
            if mapping is not None:
                upstream = await self._upstream_token_store.get(key=mapping.upstream_token_id)
        except Exception:
            logger.warning("Revocation request carried no usable grant reference")
        if upstream is not None:
            await self._revoke_at_servicenow(upstream.refresh_token, upstream.access_token)
            # Without the stored ServiceNow tokens, the MCP access and refresh
            # tokens for this grant resolve to nothing on their next use.
            await self._upstream_token_store.delete(key=upstream.upstream_token_id)
            record_revocation("revoked")
        else:
            record_revocation("unknown_grant")
        await super().revoke_token(token)

    async def _revoke_at_servicenow(self, *tokens) -> None:
        if not self._servicenow_revoke_url:
            return
        async with self._upstream_oauth_client() as oauth_client:
            secret = oauth_client.client_secret

        async def post(client, value):
            response = await client.post(
                self._servicenow_revoke_url,
                data={"token": value, "client_id": self._upstream_client_id, "client_secret": secret},
                timeout=15, follow_redirects=False,
            )
            if response.status_code >= 400:
                logger.warning("ServiceNow token revocation returned HTTP %s", response.status_code)

        for value in tokens:
            if not value:
                continue
            try:
                if self._revocation_http_client is not None:
                    await post(self._revocation_http_client, value)
                else:
                    async with httpx2.AsyncClient() as client:
                        await post(client, value)
            except httpx2.HTTPError:
                logger.warning("ServiceNow token revocation failed; the local grant is still removed")

    async def get_client(self, client_id: str):
        if self._cimd_manager is not None and self._cimd_manager.is_cimd_client_id(client_id):
            if client_id not in self._approved_clients:
                logger.warning("Rejected unapproved MCP client metadata URL")
                return None
            return await super().get_client(client_id)
        if client_id == self._upstream_client_id:
            # FastMCP would otherwise accept the ServiceNow app's own client ID
            # as an implicit client; that ID is not secret.
            return None
        if not self._allow_dynamic_registration:
            return None
        return await super().get_client(client_id)


def create_auth(settings: RemoteSettings, storage, http_client=None):
    return ServiceNowOAuthProxy(
        approved_clients=settings.approved_clients,
        allow_dynamic_registration=settings.allow_dynamic_registration,
        servicenow_revoke_url=(settings.instance + settings.revoke_path) if settings.revoke_path else "",
        revocation_http_client=http_client,
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
