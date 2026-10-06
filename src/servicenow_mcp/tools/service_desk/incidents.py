from __future__ import annotations


from fastmcp import Context, FastMCP
from servicenow_mcp.errors import OperationError
from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.tools.contracts import (
    Summary,
    PREPARE_RESULTS,
    contract_tool,
    COMMON_FIELDS,
    Limit,
    SysId,
    JournalText,
    READ_RESULTS,
    project_record,
    project_records,
)
from servicenow_mcp.tools.descriptions import (
    prepare_description,
    read_description,
    WRITE_LIFECYCLE,
)
from servicenow_mcp.tools.write_review import preview_write, return_write_errors
from .search import SearchText, IncidentNumber, SEARCH_LIMITATIONS


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @contract_tool(
        mcp,
        READ_RESULTS["incident", "list"],
        description="Search incident records by a literal short_description substring, exact number, or both (AND). "
        "Supply at least one non-null search_text or number. Supported/default fields: "
        + ", ".join(COMMON_FIELDS)
        + ". sys_id is raw, references are display names, other values are raw strings; unavailable fields may be omitted. "
        + SEARCH_LIMITATIONS,
        input_schema_extra={
            "anyOf": [
                {
                    "required": ["search_text"],
                    "properties": {"search_text": {"type": "string"}},
                },
                {"required": ["number"], "properties": {"number": {"type": "string"}}},
            ]
        },
    )
    def list_incidents(
        search_text: SearchText | None = None,
        number: IncidentNumber | None = None,
        limit: Limit = 10,
    ) -> dict:
        if search_text is None and number is None:
            raise ValueError("A title substring or incident number is required.")
        clauses = []
        if number is not None:
            clauses.append(f"number={number}")
        if search_text is not None:
            clauses.append(f"short_descriptionLIKE{search_text}")
        records = client_factory().list_records(
            "incident", query="^".join(clauses), fields=list(COMMON_FIELDS), limit=limit
        )
        records = project_records(records, "incident", COMMON_FIELDS, limit)
        return {"table": "incident", "count": len(records), "records": records}

    @contract_tool(
        mcp,
        READ_RESULTS["incident", "get"],
        description=read_description("incident", COMMON_FIELDS, collection=False)
        + "Incident details exclude attachments and journal/activity history.",
    )
    def get_incident(sys_id: SysId) -> dict:
        record = project_record(
            client_factory().get_record("incident", sys_id, fields=list(COMMON_FIELDS)),
            "incident",
        )
        if record["sys_id"].lower() != sys_id.lower():
            raise OperationError("UPSTREAM_ERROR", outcome="failed")
        return {"table": "incident", "sys_id": sys_id, "record": record}

    @contract_tool(
        mcp,
        PREPARE_RESULTS["incident", "update"],
        description="Prepare an append of work_notes, comments, or both to one incident identified by raw sys_id. "
        "Writable fields only: work_notes, comments. Supply at least one nonblank entry, trimmed and limited to 4000 characters. "
        "work_notes are internal notes; comments may be customer-visible and trigger notifications according to instance rules. "
        "Omission/null leaves that journal unchanged; empty strings cannot clear journal history. Entries append at confirmation, "
        "rather than replacing prior entries. No attachment or history editing. "
        + WRITE_LIFECYCLE,
        input_schema_extra={
            "anyOf": [
                {
                    "required": ["work_notes"],
                    "properties": {"work_notes": {"type": "string"}},
                },
                {
                    "required": ["comments"],
                    "properties": {"comments": {"type": "string"}},
                },
            ]
        },
    )
    @return_write_errors
    async def update_incident_journal(
        sys_id: SysId,
        work_notes: JournalText | None = None,
        comments: JournalText | None = None,
        *,
        ctx: Context,
    ) -> dict:
        payload = {
            key: value
            for key, value in (("work_notes", work_notes), ("comments", comments))
            if value is not None
        }
        return await preview_write(
            ctx, client_factory, "incident", payload, sys_id=sys_id
        )

    @contract_tool(
        mcp,
        PREPARE_RESULTS["incident", "insert"],
        description=prepare_description(
            "incident",
            ("short_description",),
            update=False,
            details="short_description is trimmed, nonblank and limited to 160 characters. ",
        ),
    )
    @return_write_errors
    async def create_incident(short_description: Summary, ctx: Context) -> dict:
        if not short_description or not short_description.strip():
            raise ValueError("short_description is required.")

        return await preview_write(
            ctx,
            client_factory,
            "incident",
            {"short_description": short_description.strip()},
        )

    @mcp.prompt(name="get_incident")
    def get_incident_prompt(sys_id: str) -> str:
        """Prepare a request to retrieve an incident by sys_id."""
        return (
            f"Use the get_record tool to retrieve the incident with sys_id '{sys_id}' "
            "and return its number, short_description, state, and priority."
        )
