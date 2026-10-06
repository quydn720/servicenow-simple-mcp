"""Deny caller-supplied raw queries before creating a ServiceNow client."""

from servicenow_mcp.errors import OperationError


def reject_raw_query(query: str | None) -> None:
    # No owner-exception mechanism is implemented. Fail closed for every
    # supplied string, including blanks, rather than treating it as approval.
    if query is not None:
        raise OperationError("RAW_QUERY_PROHIBITED")
