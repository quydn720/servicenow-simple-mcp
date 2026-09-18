from __future__ import annotations

from typing import Any, List, Optional

from fastmcp import FastMCP
from app.tools import ClientFactory


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
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
    
        client = client_factory()
        result = client.create_record("rm_story", payload)
        return {"table": "rm_story", "record": result}
