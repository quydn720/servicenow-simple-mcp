from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urlencode, urljoin

from fastmcp import Context, FastMCP
from servicenow_mcp.errors import OperationError
from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.tools.contracts import (
    Summary,
    PREPARE_RESULTS,
    contract_tool,
    INCIDENT_CHOICE_FIELDS,
    INCIDENT_SEARCH_FIELDS,
    INCIDENT_DETAIL_FIELDS,
    INCIDENT_DETAIL_EXCLUDED_CATEGORIES,
    IncidentRecord,
    IncidentSearchRecord,
    Offset,
    PageLimit,
    SysId,
    JournalText,
    READ_RESULTS,
)
from servicenow_mcp.tools.descriptions import (
    prepare_description,
    WRITE_LIFECYCLE,
)
from servicenow_mcp.tools.write_review import preview_write, return_write_errors
from .search import (
    INCIDENT_STATE_CODES,
    IncidentStateLabel,
    SearchText,
    IncidentNumber,
    UtcDateTime,
    PAGED_SEARCH_LIMITATIONS,
)


logger = logging.getLogger(__name__)


def _format_query_datetime(value: datetime) -> str:
    result = value.strftime("%Y-%m-%d %H:%M:%S")
    if value.microsecond:
        result += "." + f"{value.microsecond:06d}".rstrip("0")
    return result


def _incident_number_url(instance_url: str, number: str) -> str:
    if not isinstance(instance_url, str) or not instance_url:
        raise OperationError("INTERNAL_ERROR", outcome="not_attempted")
    base = urljoin(instance_url.rstrip("/") + "/", "incident_list.do")
    return f"{base}?{urlencode({'sysparm_query': f'number={number}'})}"


def _incident_search_record(record: dict, instance_url: str) -> dict:
    if not isinstance(record, dict):
        raise OperationError("UPSTREAM_ERROR", outcome="failed")
    projected = {
        field: record[field]
        for field in INCIDENT_SEARCH_FIELDS
        if field in record
    }
    number = projected.get("number")
    if not isinstance(number, str) or not number:
        raise OperationError("UPSTREAM_ERROR", outcome="failed")
    projected["url"] = _incident_number_url(instance_url, number)
    try:
        return IncidentSearchRecord.model_validate(projected).model_dump(exclude_unset=True)
    except (TypeError, ValueError):
        raise OperationError("UPSTREAM_ERROR", outcome="failed") from None


def _incident_detail_record(record: dict, instance_url: str) -> dict:
    if not isinstance(record, dict):
        raise OperationError("UPSTREAM_ERROR", outcome="failed")
    projected = {
        field: record[field]
        for field in INCIDENT_DETAIL_FIELDS
        if field in record
    }
    number = projected.get("number")
    if not isinstance(number, str) or not number:
        raise OperationError("UPSTREAM_ERROR", outcome="failed")
    projected["url"] = _incident_number_url(instance_url, number)
    try:
        return IncidentRecord.model_validate(projected).model_dump(exclude_unset=True)
    except (TypeError, ValueError):
        raise OperationError("UPSTREAM_ERROR", outcome="failed") from None


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    register_reads(mcp, client_factory)
    register_writes(mcp, client_factory)


def register_reads(mcp: FastMCP, client_factory: ClientFactory) -> None:
    """Read-only incident tools; safe for stateless remote servers.

    Tool names stay stable; contract versions are published in tool metadata.
    """

    @contract_tool(
        mcp,
        READ_RESULTS["incident", "search"],
        version="2.0.0",
        description="Search incidents using one or more of exact incident number, literal short-description substring, base-system state display label, assignment-group sys_id, caller sys_id, or sys_updated_on date bounds. Supplied filters are combined with AND. "
        "Results contain only number, short_description, state, priority, sys_updated_on, and a number-filtered ServiceNow URL; state and priority use display labels, references use display names, sys_updated_on is a raw UTC timestamp, and sys_id is omitted. "
        "Caller results remain subject to the configured ServiceNow identity's ACLs. "
        + PAGED_SEARCH_LIMITATIONS,
        input_schema_extra={
            "anyOf": [
                # Null leaves a filter unspecified, so it cannot satisfy this rule.
                {"required": [name], "properties": {name: {"not": {"type": "null"}}}}
                for name in (
                    "search_text", "number", "state", "assignment_group", "caller_id", "updated_after", "updated_before"
                )
            ]
        },
    )
    def list_incidents(
        search_text: SearchText | None = None,
        number: IncidentNumber | None = None,
        state: IncidentStateLabel | None = None,
        assignment_group: SysId | None = None,
        caller_id: SysId | None = None,
        updated_after: UtcDateTime | None = None,
        updated_before: UtcDateTime | None = None,
        limit: PageLimit = 10,
        offset: Offset = 0,
        *,
        ctx: Context,
    ) -> dict:
        filters = {
            "search_text": search_text,
            "number": number,
            "state": state,
            "assignment_group": assignment_group,
            "caller_id": caller_id,
            "updated_after": updated_after,
            "updated_before": updated_before,
        }
        filter_names = [name for name, value in filters.items() if value is not None]
        if not filter_names:
            raise ValueError("At least one incident search criterion is required.")
        if (
            updated_after is not None
            and updated_before is not None
            and updated_after >= updated_before
        ):
            raise ValueError("updated_after must be earlier than updated_before.")
        clauses = []
        if number is not None:
            clauses.append(f"number={number}")
        if search_text is not None:
            clauses.append(f"short_descriptionLIKE{search_text}")
        if state is not None:
            clauses.append(f"state={INCIDENT_STATE_CODES[state]}")
        if assignment_group is not None:
            clauses.append(f"assignment_group={assignment_group}")
        if caller_id is not None:
            clauses.append(f"caller_id={caller_id}")
        if updated_after is not None:
            clauses.append(f"sys_updated_on>={_format_query_datetime(updated_after)}")
        if updated_before is not None:
            clauses.append(f"sys_updated_on<{_format_query_datetime(updated_before)}")
        try:
            client = client_factory()
            raw_records = client.list_records(
                "incident",
                query="^".join(clauses),
                fields=list(INCIDENT_SEARCH_FIELDS),
                limit=limit,
                offset=offset,
                order_by=["ORDERBYDESCsys_updated_on", "ORDERBYsys_id"],
                display_fields=INCIDENT_CHOICE_FIELDS,
            )
            if not isinstance(raw_records, list) or len(raw_records) > limit:
                raise OperationError("UPSTREAM_ERROR", outcome="failed")
            records = [
                _incident_search_record(record, client.instance_url)
                for record in raw_records
            ]
        except Exception as error:
            code = error.code if isinstance(error, OperationError) else "INTERNAL_ERROR"
            _audit_incident_search(ctx, filter_names, "error", 0, code)
            raise
        has_more = len(records) == limit and offset + len(records) <= 100000
        _audit_incident_search(ctx, filter_names, "success", len(records))
        result = {"table": "incident", "count": len(records), "records": records}
        if has_more:
            result["next_offset"] = offset + len(records)
        return result

    @contract_tool(
        mcp,
        READ_RESULTS["incident", "detail"],
        version="3.0.0",
        description="Retrieve one incident by its approved sys_id or exact incident number. Returns only the approved incident detail fields and a number-filtered ServiceNow URL; state and priority use display labels, references use display names, and timestamps stay raw UTC. Work notes, comments, activity history, attachments, and non-allowlisted fields are excluded; omitted allowlisted fields are identified without inferring why they were absent. Access is enforced by the configured ServiceNow execution identity and ACLs. Read-only; no caller-selected fields or raw queries.",
        input_schema_extra={
            "oneOf": [
                {
                    "required": ["sys_id"],
                    "properties": {
                        "sys_id": {"not": {"type": "null"}},
                        "number": {"type": "null"},
                    },
                },
                {
                    "required": ["number"],
                    "properties": {
                        "sys_id": {"type": "null"},
                        "number": {"not": {"type": "null"}},
                    },
                },
            ]
        },
    )
    def get_incident(
        sys_id: SysId | None = None,
        number: IncidentNumber | None = None,
    ) -> dict:
        if (sys_id is None) == (number is None):
            raise ValueError("Supply exactly one of sys_id or number.")
        try:
            client = client_factory()
            if number is not None:
                records = client.list_records(
                    "incident",
                    query=f"number={number}",
                    fields=list(INCIDENT_DETAIL_FIELDS),
                    limit=2,
                    display_fields=INCIDENT_CHOICE_FIELDS,
                )
                if not isinstance(records, list):
                    raise OperationError("UPSTREAM_ERROR", outcome="failed")
                if not records:
                    raise OperationError("NOT_FOUND", outcome="failed")
                if len(records) != 1 or not isinstance(records[0], dict):
                    raise OperationError("UPSTREAM_ERROR", outcome="failed")
                source = records[0]
                if source.get("number") != number:
                    raise OperationError("UPSTREAM_ERROR", outcome="failed")
            else:
                assert sys_id is not None
                source = client.get_record(
                    "incident",
                    sys_id,
                    fields=["sys_id", *INCIDENT_DETAIL_FIELDS],
                    display_fields=INCIDENT_CHOICE_FIELDS,
                )
                if not isinstance(source, dict):
                    raise OperationError("UPSTREAM_ERROR", outcome="failed")
                actual_id = source.get("sys_id")
                if not isinstance(actual_id, str) or actual_id.lower() != sys_id.lower():
                    raise OperationError("UPSTREAM_ERROR", outcome="failed")
            record = _incident_detail_record(source, client.instance_url)
            result = {
                "table": "incident",
                "record": record,
                "redaction": {
                    "excluded_categories": list(INCIDENT_DETAIL_EXCLUDED_CATEGORIES),
                    "omitted_fields": [
                        field for field in INCIDENT_DETAIL_FIELDS if field not in record
                    ],
                },
            }
        except Exception as error:
            code = error.code if isinstance(error, OperationError) else "INTERNAL_ERROR"
            _audit_incident_detail("error", code)
            raise
        _audit_incident_detail("success")
        return result

    @mcp.prompt(name="get_incident")
    def get_incident_prompt(sys_id: str) -> str:
        """Prepare a request to retrieve an incident by sys_id."""
        return (
            f"Use the get_record tool to retrieve the incident with sys_id '{sys_id}' "
            "and return its number, short_description, state, and priority."
        )


def register_writes(mcp: FastMCP, client_factory: ClientFactory) -> None:
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



def _audit_incident_search(ctx, filter_names, outcome, result_count, error_code=None):
    """Write a structured, value-free audit event for incident searches."""
    event = {
        "event": "incident_search",
        "tool": "list_incidents",
        "tool_version": "2.0.0",
        "operation": "search",
        "identity": getattr(ctx, "client_id", None) or "unavailable",
        "filters": sorted(filter_names),
        "outcome": outcome,
        "result_count": result_count,
    }
    if error_code:
        event["error_code"] = error_code
    logger.info("Incident search audit", extra={"incident_search_audit": event})


def _audit_incident_detail(outcome, error_code=None):
    """Write a value-free audit event for incident detail retrieval."""
    event = {
        "event": "incident_detail_retrieval",
        "tool": "get_incident",
        "tool_version": "3.0.0",
        "operation": "read",
        "identity": "unavailable",
        "outcome": outcome,
    }
    if error_code:
        event["error_code"] = error_code
    logger.info("Incident detail retrieval audit", extra={"incident_detail_audit": event})
