from __future__ import annotations

from typing import Any, List, Optional

from fastmcp import FastMCP
from app.tools import ClientFactory


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
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
    
        client = client_factory()
        result = client.create_record("task", payload)
        return {"table": "task", "record": result}
