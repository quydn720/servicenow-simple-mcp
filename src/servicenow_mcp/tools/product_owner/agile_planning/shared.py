import re
from typing import Any, List, Optional

from fastmcp import FastMCP
from servicenow_mcp.tools import ClientFactory


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


def register_reads(mcp: FastMCP, client_factory: ClientFactory,
                   entity: str, plural: str, table: str, default_fields: List[str]) -> None:
    @mcp.tool(name=f"get_agile_{entity}", description=f"Get an Agile {entity} by ServiceNow sys_id.")
    def get(sys_id: str, fields: Optional[List[str]] = None) -> dict:
        sys_id = reference(sys_id, "sys_id")
        record = client_factory().get_record(
            table=table, sys_id=sys_id,
            fields=default_fields if fields is None else fields,
        )
        return {"table": table, "sys_id": sys_id, "record": record}

    @mcp.tool(name=f"list_agile_{plural}", description=f"List Agile {plural}, optionally using a ServiceNow encoded query. Reference fields contain display names.")
    def list_items(query: Optional[str] = None, fields: Optional[List[str]] = None, limit: int = 10) -> dict:
        records = client_factory().list_records(
            table=table, query=query,
            fields=default_fields if fields is None else fields, limit=limit,
        )
        return {"table": table, "count": len(records), "records": records}
