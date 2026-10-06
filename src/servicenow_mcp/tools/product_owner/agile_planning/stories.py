from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP
from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.tools.contracts import (
    Summary,
    Text,
    Priority,
    SysId,
    ClearableSysId,
    Points,
    PREPARE_RESULTS,
    contract_tool,
)
from servicenow_mcp.tools.descriptions import prepare_description
from servicenow_mcp.tools.write_review import preview_write, return_write_errors
from .shared import reference, register_reads, title, update_payload, validate_points


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    register_reads(
        mcp,
        client_factory,
        "story",
        "stories",
        "rm_story",
        [
            "sys_id",
            "number",
            "short_description",
            "description",
            "acceptance_criteria",
            "story_points",
            "priority",
            "product",
            "epic",
        ],
    )

    @contract_tool(
        mcp,
        PREPARE_RESULTS["rm_story", "insert"],
        description=prepare_description(
            "rm_story",
            (
                "short_description",
                "description",
                "acceptance_criteria",
                "story_points",
                "priority",
                "product",
                "epic",
            ),
            update=False,
            details="short_description is trimmed, nonblank and limited to 160 characters. Text fields are trimmed and limited to 4000 characters. Priority accepts raw choice codes 1–5. Priority defaults to 3. Product and epic require raw sys_ids; acceptance_criteria supports HTML. Story points must be an integer 0–100. ",
        ),
    )
    @return_write_errors
    async def create_agile_story(
        short_description: Summary,
        description: Text | None = None,
        acceptance_criteria: Text | None = None,
        story_points: Points | None = None,
        priority: Priority = "3",
        product: SysId | None = None,
        epic: SysId | None = None,
        *,
        ctx: Context,
    ) -> dict:
        short_description = title(short_description)
        validate_points(story_points)

        payload: dict[str, Any] = {
            "short_description": short_description.strip(),
            "priority": priority,
        }

        if description is not None:
            payload["description"] = description.strip()
        if acceptance_criteria is not None:
            payload["acceptance_criteria"] = acceptance_criteria.strip()
        if story_points is not None:
            payload["story_points"] = story_points
        for field, value in (("product", product), ("epic", epic)):
            if value is not None:
                payload[field] = reference(value, field)

        return await preview_write(ctx, client_factory, "rm_story", payload)

    @contract_tool(
        mcp,
        PREPARE_RESULTS["rm_story", "update"],
        description=prepare_description(
            "rm_story",
            (
                "short_description",
                "description",
                "acceptance_criteria",
                "story_points",
                "priority",
                "product",
                "epic",
            ),
            update=True,
            details="short_description is trimmed, nonblank and limited to 160 characters. Text fields are trimmed and limited to 4000 characters. Priority accepts raw choice codes 1–5. Product and epic require raw sys_ids; acceptance_criteria supports HTML. Story points must be an integer 0–100. ",
        ),
    )
    @return_write_errors
    async def update_agile_story(
        sys_id: SysId,
        short_description: Summary | None = None,
        description: Text | None = None,
        acceptance_criteria: Text | None = None,
        story_points: Points | None = None,
        priority: Priority | None = None,
        product: ClearableSysId | None = None,
        epic: ClearableSysId | None = None,
        *,
        ctx: Context,
    ) -> dict:
        sys_id = reference(sys_id, "sys_id")
        payload = update_payload(
            short_description=short_description,
            description=description,
            acceptance_criteria=acceptance_criteria,
            story_points=story_points,
            priority=priority,
            product=product,
            epic=epic,
        )
        return await preview_write(
            ctx, client_factory, "rm_story", payload, sys_id=sys_id
        )
