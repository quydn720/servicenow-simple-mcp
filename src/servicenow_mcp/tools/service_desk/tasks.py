from __future__ import annotations

from typing import Any, Optional

from fastmcp import Context, FastMCP
from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.tools.write_review import preview_write, return_write_errors


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool()
    @return_write_errors
    async def create_task(short_description: str, description: Optional[str] = None, priority: str = "3", assignment_group: Optional[str] = None, *, ctx: Context) -> dict:
        """Prepare a preview for user review before creating a ServiceNow task with a narrow, safe payload."""
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
    
        return await preview_write(ctx, client_factory, "task", payload)
