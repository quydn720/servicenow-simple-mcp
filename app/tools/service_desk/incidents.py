from __future__ import annotations

from typing import Any, List, Optional

from fastmcp import FastMCP
from app.tools import ClientFactory


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool()
    def create_incident(short_description: str) -> dict:
        """Create a ServiceNow incident with a required short description."""
        if not short_description or not short_description.strip():
            raise ValueError("short_description is required.")
    
        client = client_factory()
        result = client.create_record(
            "incident",
            {"short_description": short_description.strip()},
        )
        return {"table": "incident", "record": result}

    @mcp.prompt()
    def get_incident(sys_id: str) -> str:
        """Prepare a request to retrieve an incident by sys_id."""
        return (
            f"Use the get_record tool to retrieve the incident with sys_id '{sys_id}' "
            "and return its number, short_description, state, and priority."
        )
