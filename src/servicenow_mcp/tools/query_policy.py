"""Deny caller-supplied raw queries before creating a ServiceNow client."""

from fastmcp.exceptions import ToolError


def reject_raw_query(query: str | None) -> None:
    # No owner-exception mechanism is implemented. Fail closed for every
    # supplied string, including blanks, rather than treating it as approval.
    if query is not None:
        raise ToolError(
            "RAW_QUERY_PROHIBITED: Caller-supplied ServiceNow queries are disabled. "
            "Omit query or pass null to list records without a filter. "
            "Owner-approved query exceptions are not implemented."
        )
