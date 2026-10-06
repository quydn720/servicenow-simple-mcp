"""Two-step preview and confirmation for ServiceNow write tools."""

from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from weakref import WeakKeyDictionary

from fastmcp import Context, FastMCP

from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.errors import OperationError, error_envelope
from servicenow_mcp.tools.contracts import (
    CONFIRM_RESULT,
    PreviewId,
    Confirmed,
    contract_tool,
    normalize_payload,
    project_record,
)

PREVIEW_TTL_SECONDS = 600
MAX_PENDING_PREVIEWS = 1000
WRITE_INSTRUCTIONS = (
    "ServiceNow create/update tools only prepare record previews. When a tool returns "
    "status=awaiting_confirmation, show the complete preview to the user and ask for "
    "explicit approval. Stop and wait for the user's next reply. Never infer approval "
    "from the original create/update request, tool permissions, or another preview. "
    "Only after approval call confirm_pending_write with the returned preview_id and "
    "confirmed=true. On rejection call it with confirmed=false. If fields change, "
    "prepare a new preview and ask again. Report errors; never automatically retry writes."
)


@dataclass
class PendingWrite:
    session_id: str
    preview: dict
    client_factory: ClientFactory
    expires_at: float


class PreviewStore:
    def __init__(self):
        self.pending: dict[str, PendingWrite] = {}
        self.lock = Lock()

    def prune(self):
        now = monotonic()
        for token, pending in list(self.pending.items()):
            if pending.expires_at <= now:
                del self.pending[token]


# State is isolated per server and session, and disappears on server restart.
_stores: WeakKeyDictionary = WeakKeyDictionary()


def return_write_errors(fn):
    """Return safe structured preparation errors; contract_tool sets isError."""

    @wraps(fn)
    async def wrapped(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception as error:
            return error_envelope(error)

    return wrapped


async def preview_write(
    ctx: Context,
    client_factory: ClientFactory,
    table: str,
    payload: dict,
    *,
    sys_id: str | None = None,
) -> dict:
    request_context = getattr(ctx, "request_context", None)
    protocol_version = getattr(request_context, "protocol_version", None)
    if protocol_version is not None and protocol_version >= "2026-07-28":
        raise OperationError("SESSION_REQUIRED")
    payload = normalize_payload(
        table, "update" if sys_id is not None else "insert", payload
    )
    preview = {
        "operation": "update" if sys_id is not None else "insert",
        "table": table,
        "fields": deepcopy(payload),
    }
    if sys_id is not None:
        preview["sys_id"] = sys_id
    store = _stores[ctx.fastmcp]
    with store.lock:
        store.prune()
        if len(store.pending) >= MAX_PENDING_PREVIEWS:
            raise OperationError("PREVIEW_LIMIT_EXCEEDED")
        token = token_urlsafe(32)
        store.pending[token] = PendingWrite(
            ctx.session_id,
            deepcopy(preview),
            client_factory,
            monotonic() + PREVIEW_TTL_SECONDS,
        )
    return {
        "status": "awaiting_confirmation",
        "preview_id": token,
        "preview": preview,
        "expires_in_seconds": PREVIEW_TTL_SECONDS,
        "message": "No write was made. Show this complete preview to the user and ask "
        "for explicit confirmation. Wait for their reply before calling "
        "confirm_pending_write(preview_id, confirmed=true). If rejected, "
        "call with confirmed=false. Changed values require a new preview.",
    }


def register_write_review(mcp: FastMCP) -> None:
    store = PreviewStore()
    _stores[mcp] = store

    @contract_tool(mcp, CONFIRM_RESULT)
    @return_write_errors
    async def confirm_pending_write(
        preview_id: PreviewId, confirmed: Confirmed, ctx: Context
    ) -> dict:
        """Commit the saved preview ONLY after the user reviewed it and explicitly approved in a subsequent chat reply. Pass confirmed=false to cancel. Never infer approval from the initial request. Preview IDs expire after 10 minutes and are single-use; values cannot be changed here."""
        if confirmed is not True and confirmed is not False:
            raise ValueError("confirmed must be a boolean.")
        with store.lock:
            store.prune()
            pending = store.pending.get(preview_id)
            if pending is None or pending.session_id != ctx.session_id:
                raise OperationError("CONFIRMATION_INVALID")
            # Consume before the API call to prevent concurrent/replayed inserts,
            # even if the response is lost after ServiceNow commits the write.
            del store.pending[preview_id]
        preview = pending.preview
        if not confirmed:
            return {
                "status": "cancelled",
                "preview": deepcopy(preview),
                "message": "Write not confirmed; no write was made.",
            }
        attempted = False
        try:
            client = pending.client_factory()
            payload = deepcopy(preview["fields"])
            attempted = True
            if preview["operation"] == "insert":
                record = client.create_record(preview["table"], payload)
            else:
                record = client.update_record(
                    preview["table"], preview["sys_id"], payload
                )
            record = project_record(record, preview["table"], failure_outcome="unknown")
            return {"table": preview["table"], "record": record}
        except Exception as error:
            if attempted and not isinstance(error, OperationError):
                error = OperationError("INTERNAL_ERROR", outcome="unknown")
            result = error_envelope(error, confirmation=True)
            result["preview"] = deepcopy(preview)
            result["retry_guidance"] = (
                "This preview is consumed. Verify the instance before preparing a new preview; the write may already have committed."
                if result["outcome"] == "unknown"
                else "This preview is consumed. Resolve the error, then prepare and approve a new preview. Never automatically retry the write."
            )
            return result
