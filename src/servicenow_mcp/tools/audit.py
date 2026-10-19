"""Identity fields for value-free audit events."""

from __future__ import annotations

from fastmcp.server.dependencies import get_access_token


def audit_identity(ctx=None) -> dict:
    """Return who acted, never request values.

    On the remote server this is the ServiceNow user whose token the broker
    verified for this request. On local stdio every call uses the configured
    integration account. The MCP client's ID is recorded separately.
    """
    try:
        token = get_access_token()
    except RuntimeError:
        token = None
    if token is not None and token.claims.get("provider") == "servicenow" and token.subject:
        fields = {"identity": token.subject, "identity_type": "servicenow_user"}
    else:
        fields = {"identity": "configured_integration_account", "identity_type": "integration_account"}
    fields["client"] = getattr(ctx, "client_id", None) or "unavailable"
    return fields
