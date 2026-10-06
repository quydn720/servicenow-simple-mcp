"""Safe, explicit error classification shared by tools and ServiceNow clients."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ErrorCode = Literal[
    "VALIDATION_ERROR",
    "AUTHENTICATION_REQUIRED",
    "PERMISSION_DENIED",
    "NOT_FOUND",
    "RAW_QUERY_PROHIBITED",
    "CONFIRMATION_INVALID",
    "SESSION_REQUIRED",
    "PREVIEW_LIMIT_EXCEEDED",
    "UPSTREAM_ERROR",
    "TIMEOUT",
    "INTERNAL_ERROR",
]
Outcome = Literal["not_attempted", "failed", "unknown"]
MESSAGES = {
    "VALIDATION_ERROR": "Invalid tool arguments. Check required fields, types, allowed values, and limits.",
    "AUTHENTICATION_REQUIRED": "ServiceNow authentication is unavailable or invalid. Restore authentication before retrying.",
    "PERMISSION_DENIED": "Access is denied for this operation. Verify the required permissions.",
    "NOT_FOUND": "The resource is unavailable or not accessible. Check the identifier and your access.",
    "RAW_QUERY_PROHIBITED": "Caller-supplied ServiceNow queries are disabled. Omit query or pass null. Owner-approved query exceptions are not implemented.",
    "CONFIRMATION_INVALID": "Preview not found, expired, already used, or unavailable in this session. Prepare and review a new preview.",
    "SESSION_REQUIRED": "Previews require a session-based connection. Reconnect using FastMCP Client mode='legacy'.",
    "PREVIEW_LIMIT_EXCEEDED": "Too many pending previews. Cancel a preview or wait for expiration.",
    "UPSTREAM_ERROR": "ServiceNow could not complete the operation. Check connectivity and service availability.",
    "TIMEOUT": "ServiceNow did not return a definitive response before the deadline.",
    "INTERNAL_ERROR": "An unexpected server error occurred. Contact the tool owner.",
}


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["error"] = Field(description="Tool execution failed.")
    code: ErrorCode = Field(description="Stable error code.")
    message: str = Field(
        min_length=1,
        description="Safe explanation and recovery guidance; never raw exception text.",
    )
    retryable: bool = Field(
        description="Whether repeating the unchanged call is safe and potentially useful; always false for writes."
    )
    outcome: Outcome = Field(
        description="not_attempted: no record operation dispatched; failed: definitive failure; unknown: a dispatched write may have committed."
    )
    http_status: int = Field(
        default=None,
        ge=100,
        le=599,
        description="Upstream HTTP status when safely available.",
    )


class OperationError(RuntimeError):
    """Internal exception carrying only approved messages and explicit state."""

    def __init__(
        self,
        code: ErrorCode,
        *,
        outcome: Outcome = "not_attempted",
        retryable=False,
        http_status=None,
    ):
        self.code = code
        self.outcome = outcome
        self.retryable = retryable
        self.http_status = http_status
        message = MESSAGES[code]
        if http_status is not None:
            message += f" (HTTP {http_status})"
        super().__init__(message)


def error_envelope(error, *, confirmation=False, fallback_outcome="not_attempted"):
    if isinstance(error, OperationError):
        code, outcome, retryable, http_status = (
            error.code,
            error.outcome,
            error.retryable,
            error.http_status,
        )
    elif isinstance(error, (ValidationError, ValueError)):
        code, outcome, retryable, http_status = (
            "VALIDATION_ERROR",
            "not_attempted",
            False,
            None,
        )
    else:
        code, outcome, retryable, http_status = (
            "INTERNAL_ERROR",
            fallback_outcome,
            False,
            None,
        )
    data = {
        "status": "error",
        "code": code,
        "message": MESSAGES[code],
        "retryable": False if confirmation else retryable,
        "outcome": outcome,
    }
    if http_status is not None:
        data["http_status"] = http_status
    return ErrorEnvelope.model_validate(data).model_dump(exclude_unset=True)
