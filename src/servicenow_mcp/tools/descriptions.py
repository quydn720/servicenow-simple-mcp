"""Published tool descriptions shared across feature groups."""

from servicenow_mcp.tools.contracts import COMMON_FIELDS, STORY_FIELDS, EPIC_FIELDS


def read_description(tables: str, fields, *, collection: bool) -> str:
    purpose = (
        f"List records from {tables} when browsing available records. "
        if collection
        else f"Read one record from {tables} by raw sys_id when its identifier is known. "
    )
    limits = (
        "Limit defaults to 10 and must be 1–100. Order is determined by ServiceNow "
        "and is not guaranteed; count is the returned count, not the total. There "
        "is no truncation indicator: a full page may have more matches. No pagination. "
        "Raw queries are prohibited: omit query or pass null. Structured filters "
        "and owner-approved query exceptions are not implemented. "
        if collection
        else "Returns at most one record; no bulk reads, filters, raw queries, scripts, or pagination. "
    )
    return (
        purpose + f"Supported/default fields: {', '.join(fields)}. Field selection is "
        "allowlisted; sys_id is always included. References are display names; "
        "other returned values are raw strings and unavailable fields may be omitted. "
        + limits
        + "Read-only: no record writes or confirmation. Only retry errors marked "
        "retryable=true; validation, authorization, and missing-record errors "
        "require resolution first."
    )


WRITE_LIFECYCLE = (
    "Returns one saved preview; no ServiceNow call or record write occurs during "
    "preparation. Show the complete preview and wait for explicit approval in a "
    "subsequent user reply, then call confirm_pending_write with confirmed=true; "
    "confirmed=false cancels. Initial requests do not count as approval. Previews "
    "expire after 600 seconds, are single-use and bound to the originating server "
    "and session; restart discards them and stateless connections are unsupported. "
    "Changed fields require a new preview and approval. Confirmation is conversational: "
    "the server cannot independently verify human approval. Never automatically "
    "retry writes; if outcome=unknown, verify the instance before preparing and "
    "approving another preview. No bulk writes, deletes, raw queries, or scripts."
)


def prepare_description(
    table: str, fields, *, update: bool = False, details: str = ""
) -> str:
    operation = "updating" if update else "creating"
    validation = (
        "Supply a raw target sys_id and at least one changed field. Omission/null "
        "leaves fields unchanged; empty strings clear "
        + ", ".join(
            field
            for field in fields
            if field in ("description", "acceptance_criteria", "product", "epic")
        )
        + ", but short_description cannot be empty. "
        if update
        else "Omission/null leaves optional fields out of the payload; ServiceNow "
        "may apply defaults at confirmation. "
    )
    return (
        f"Prepare a preview before {operation} one record in {table}. "
        f"Writable fields only: {', '.join(fields)}. "
        + validation
        + details
        + WRITE_LIFECYCLE
    )


CONFIRM_DESCRIPTION = (
    "Commit or cancel one saved insert/update preview after the user reviewed its "
    "complete payload and explicitly approved in a subsequent reply. Supported "
    "tables/writable fields: incident (short_description); task (short_description, "
    "description, priority, assignment_group); rm_story (short_description, "
    "description, acceptance_criteria, story_points, priority, product, epic); "
    "rm_epic (short_description, description, product, priority). Updates are "
    "supported only for rm_story and rm_epic. No replacement fields are accepted; "
    "only the exact saved payload is approved. confirmed=false cancels without "
    "writing; confirmed=true attempts one write and consumes the ID before the "
    "attempt, including failures. Previews expire after 600 seconds, are single-use "
    "and bound to the originating server/session; restart discards them and stateless "
    "connections are unsupported. Changed values require a fresh preview and approval. "
    "Never infer approval from the initial request. Confirmation is conversational: "
    "the server cannot independently verify human approval. Never automatically "
    "retry writes. If outcome=unknown, the write may have committed: verify the "
    "instance before preparing and approving another preview. Returns at most one "
    "record; ServiceNow defaults and business rules may change persisted values. "
    "Returned fields are limited by table: incident/task ("
    + ", ".join(COMMON_FIELDS)
    + "); rm_story ("
    + ", ".join(STORY_FIELDS)
    + "); rm_epic ("
    + ", ".join(EPIC_FIELDS)
    + "). sys_id is raw; references are display names, other values are raw strings "
    "and unavailable fields may be omitted. No bulk writes, deletes, pagination, "
    "raw queries, or scripts."
)
