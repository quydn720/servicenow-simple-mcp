from __future__ import annotations

from typing import Any, Optional

from fastmcp import Context, FastMCP
from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.tools.write_review import preview_write, return_write_errors
from .shared import reference, register_reads, title, update_payload, validate_points


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    register_reads(mcp, client_factory, "story", "stories", "rm_story", [
        "sys_id", "number", "short_description", "description", "acceptance_criteria",
        "story_points", "priority", "product", "epic",
    ])
    @mcp.tool()
    @return_write_errors
    async def create_agile_story(
        short_description: str,
        description: Optional[str] = None,
        acceptance_criteria: Optional[str] = None,
        story_points: Optional[int] = None,
        priority: str = "3",
        product: Optional[str] = None,
        epic: Optional[str] = None,
        *, ctx: Context,
    ) -> dict:
        """Prepare a preview for user review before creating an Agile story. Product and epic accept sys_ids from Agile lookup tools; acceptance criteria supports HTML."""
        short_description = title(short_description)
        validate_points(story_points)

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
        for field, value in (("product", product), ("epic", epic)):
            if value is not None:
                payload[field] = reference(value, field)

        return await preview_write(ctx, client_factory, "rm_story", payload)

    @mcp.tool()
    @return_write_errors
    async def update_agile_story(
        sys_id: str,
        short_description: Optional[str] = None,
        description: Optional[str] = None,
        acceptance_criteria: Optional[str] = None,
        story_points: Optional[int] = None,
        priority: Optional[str] = None,
        product: Optional[str] = None,
        epic: Optional[str] = None,
        *, ctx: Context,
    ) -> dict:
        """Prepare a preview for user review before updating a story by sys_id. None leaves fields unchanged; empty text/reference strings clear them. References accept sys_ids; acceptance criteria supports HTML."""
        sys_id = reference(sys_id, "sys_id")
        payload = update_payload(
            short_description=short_description, description=description,
            acceptance_criteria=acceptance_criteria, story_points=story_points,
            priority=priority, product=product, epic=epic,
        )
        return await preview_write(ctx, client_factory, "rm_story", payload, sys_id=sys_id)
