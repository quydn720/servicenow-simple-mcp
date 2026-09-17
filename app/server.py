from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv
from fastmcp import FastMCP

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from app.config import Settings
from app.service_now_client import ServiceNowClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

mcp = FastMCP("servicenow-pdi")


def get_client() -> ServiceNowClient:
    settings = Settings.from_env()
    return ServiceNowClient(settings)


@mcp.tool()
def list_records(table: str, query: Optional[str] = None, fields: Optional[List[str]] = None, limit: int = 10) -> dict:
    """List records from a ServiceNow table. Restrict to known tables and safe fieldsets in production."""
    if not table or not table.strip():
        raise ValueError("The table name is required.")

    allowed_tables = {"incident", "task", "sc_task", "problem", "change_request"}
    if table.lower() not in allowed_tables:
        raise ValueError(f"Table '{table}' is not allowed in this starter configuration.")

    client = get_client()
    records = client.list_records(table=table, query=query, fields=fields, limit=limit)
    return {"table": table, "count": len(records), "records": records}


@mcp.tool()
def get_record(table: str, sys_id: str, fields: Optional[List[str]] = None) -> dict:
    """Fetch a single ServiceNow record by sys_id."""
    if not table or not table.strip():
        raise ValueError("The table name is required.")
    if not sys_id or not sys_id.strip():
        raise ValueError("The sys_id is required.")

    allowed_tables = {"incident", "task", "sc_task", "problem", "change_request"}
    if table.lower() not in allowed_tables:
        raise ValueError(f"Table '{table}' is not allowed in this starter configuration.")

    client = get_client()
    record = client.get_record(table=table, sys_id=sys_id, fields=fields)
    return {"table": table, "sys_id": sys_id, "record": record}


@mcp.tool()
def create_task(short_description: str, description: Optional[str] = None, priority: str = "3", assignment_group: Optional[str] = None) -> dict:
    """Create a ServiceNow task with a narrow, safe payload."""
    if not short_description or not short_description.strip():
        raise ValueError("short_description is required.")

    payload: dict[str, Any] = {
        "short_description": short_description.strip(),
        "priority": priority,
    }

    if description:
        payload["description"] = description.strip()
    if assignment_group:
        payload["assignment_group"] = assignment_group.strip()

    client = get_client()
    result = client.create_record("task", payload)
    return {"table": "task", "record": result}


@mcp.tool()
def create_incident(short_description: str) -> dict:
    """Create a ServiceNow incident with a required short description."""
    if not short_description or not short_description.strip():
        raise ValueError("short_description is required.")

    client = get_client()
    result = client.create_record(
        "incident",
        {"short_description": short_description.strip()},
    )
    return {"table": "incident", "record": result}


@mcp.tool()
def create_agile_story(
    short_description: str,
    description: Optional[str] = None,
    acceptance_criteria: Optional[str] = None,
    story_points: Optional[int] = None,
    priority: str = "3",
) -> dict:
    """Create an Agile story in ServiceNow's rm_story table."""
    if not short_description or not short_description.strip():
        raise ValueError("short_description is required.")
    if story_points is not None and not 0 <= story_points <= 100:
        raise ValueError("story_points must be between 0 and 100.")

    payload: dict[str, Any] = {
        "short_description": short_description.strip(),
        "priority": priority,
    }

    if description:
        payload["description"] = description.strip()
    if acceptance_criteria:
        payload["acceptance_criteria"] = acceptance_criteria.strip()
    if story_points is not None:
        payload["story_points"] = story_points

    client = get_client()
    result = client.create_record("rm_story", payload)
    return {"table": "rm_story", "record": result}


@mcp.prompt()
def get_incident(sys_id: str) -> str:
    """Prepare a request to retrieve an incident by sys_id."""
    return (
        f"Use the get_record tool to retrieve the incident with sys_id '{sys_id}' "
        "and return its number, short_description, state, and priority."
    )


if __name__ == "__main__":
    # The server runs in stdio mode by default for MCP clients.
    mcp.run()
