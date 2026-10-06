"""Read-only change status retrieval."""

from fastmcp import FastMCP
from servicenow_mcp.errors import OperationError
from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.tools.contracts import (
    CHANGE_STATUS_FIELDS,
    ChangeStatusRecord,
    READ_RESULTS,
    SysId,
    contract_tool,
)
from pydantic import ValidationError


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @contract_tool(
        mcp,
        READ_RESULTS["change_status", "get"],
        description="Retrieve current status of one change_request by raw sys_id. Supported/default fields: "
        + ", ".join(CHANGE_STATUS_FIELDS)
        + ". Returns at most one record; sys_id is raw and other values are raw strings. "
        "State, approval, and type are raw instance choice codes, not interpreted lifecycle labels; unavailable fields may be omitted. "
        "Read-only: no record writes, transition, approval, or confirmation. No bulk reads, pagination, raw queries, or scripts. "
        "Only retry errors marked retryable=true; resolve validation, authorization, or missing-record errors first.",
    )
    def get_change_status(sys_id: SysId) -> dict:
        record = client_factory().get_record(
            "change_request", sys_id, fields=list(CHANGE_STATUS_FIELDS)
        )
        if not isinstance(record, dict):
            raise OperationError("UPSTREAM_ERROR", outcome="failed")
        projected = {
            key: value for key, value in record.items() if key in CHANGE_STATUS_FIELDS
        }
        try:
            ChangeStatusRecord.model_validate(projected)
        except ValidationError:
            raise OperationError("UPSTREAM_ERROR", outcome="failed") from None
        if projected["sys_id"].lower() != sys_id.lower():
            raise OperationError("UPSTREAM_ERROR", outcome="failed")
        return {"table": "change_request", "sys_id": sys_id, "record": projected}
