from servicenow_mcp.tools.descriptions import read_description

import re
from typing import Any, List, Optional

from fastmcp import FastMCP
from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.errors import OperationError
from servicenow_mcp.tools.query_policy import reject_raw_query
from servicenow_mcp.tools.contracts import (
    SysId,
    StoryFields,
    EpicFields,
    ProductFields,
    RawQuery,
    Limit,
    READ_RESULTS,
    contract_tool,
    project_record,
    project_records,
    select_fields,
)


def reference(value: str, field: str, allow_empty: bool = False) -> str:
    value = value.strip()
    if allow_empty and not value:
        return ""
    if not re.fullmatch(r"[0-9a-fA-F]{32}", value):
        raise ValueError(f"{field} must be a 32-character hexadecimal sys_id.")
    return value


def title(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("short_description is required.")
    return value.strip()


def validate_points(value: Optional[int]) -> None:
    if value is not None and not 0 <= value <= 100:
        raise ValueError("story_points must be between 0 and 100.")


def update_payload(**values: Any) -> dict:
    payload = {}
    for field, value in values.items():
        if value is None:
            continue
        if field == "short_description":
            value = title(value)
        elif field in ("product", "epic"):
            value = reference(value, field, allow_empty=True)
        elif field == "story_points":
            validate_points(value)
        elif field != "priority":
            value = value.strip()
        payload[field] = value
    if not payload:
        raise ValueError("At least one field must be supplied for update.")
    return payload


def register_reads(
    mcp: FastMCP,
    client_factory: ClientFactory,
    entity: str,
    plural: str,
    table: str,
    default_fields: List[str],
) -> None:
    FieldSelection = {
        "story": StoryFields,
        "epic": EpicFields,
        "product": ProductFields,
    }[entity]

    @contract_tool(
        mcp,
        READ_RESULTS[entity, "get"],
        name=f"get_agile_{entity}",
        description=read_description(table, default_fields, collection=False),
    )
    def get(sys_id: SysId, fields: FieldSelection | None = None) -> dict:
        sys_id = reference(sys_id, "sys_id")
        selected = select_fields(fields, default_fields)
        record = client_factory().get_record(
            table=table,
            sys_id=sys_id,
            fields=selected,
        )
        record = project_record(record, table, selected)
        if record["sys_id"].lower() != sys_id.lower():
            raise OperationError("UPSTREAM_ERROR", outcome="failed")
        return {"table": table, "sys_id": sys_id, "record": record}

    @contract_tool(
        mcp,
        READ_RESULTS[entity, "list"],
        name=f"list_agile_{plural}",
        description=read_description(table, default_fields, collection=True),
    )
    def list_items(
        query: RawQuery = None, fields: FieldSelection | None = None, limit: Limit = 10
    ) -> dict:
        reject_raw_query(query)
        selected = select_fields(fields, default_fields)
        records = client_factory().list_records(
            table=table,
            query=None,
            fields=selected,
            limit=limit,
        )
        records = project_records(records, table, selected, limit)
        return {"table": table, "count": len(records), "records": records}
