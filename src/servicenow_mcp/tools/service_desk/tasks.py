from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP
from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.tools.contracts import (
    Summary,
    PREPARE_RESULTS,
    contract_tool,
)
from servicenow_mcp.tools.contracts import Text, Priority, SysId
from servicenow_mcp.tools.descriptions import prepare_description
from servicenow_mcp.tools.write_review import preview_write, return_write_errors


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @contract_tool(
        mcp,
        PREPARE_RESULTS["task", "insert"],
        description=prepare_description(
            "task",
            ("short_description", "description", "priority", "assignment_group"),
            update=False,
            details="short_description is trimmed, nonblank and limited to 160 characters. Text fields are trimmed and limited to 4000 characters. Priority accepts raw choice codes 1–5. assignment_group requires a raw sys_id; priority defaults to raw choice code 3. ",
        ),
    )
    @return_write_errors
    async def create_task(
        short_description: Summary,
        description: Text | None = None,
        priority: Priority = "3",
        assignment_group: SysId | None = None,
        *,
        ctx: Context,
    ) -> dict:
        if not short_description or not short_description.strip():
            raise ValueError("short_description is required.")

        payload: dict[str, Any] = {
            "short_description": short_description.strip(),
            "priority": priority,
        }

        if description is not None:
            payload["description"] = description.strip()
        if assignment_group:
            payload["assignment_group"] = assignment_group.strip()

        return await preview_write(ctx, client_factory, "task", payload)
