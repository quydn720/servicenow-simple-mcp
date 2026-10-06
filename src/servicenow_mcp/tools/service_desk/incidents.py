from __future__ import annotations


from fastmcp import Context, FastMCP
from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.tools.write_review import preview_write, return_write_errors


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool()
    @return_write_errors
    async def create_incident(short_description: str, ctx: Context) -> dict:
        """Prepare a preview for user review before creating a ServiceNow incident with a required short description."""
        if not short_description or not short_description.strip():
            raise ValueError("short_description is required.")
    
        return await preview_write(ctx, client_factory, "incident",
                                   {"short_description": short_description.strip()})

    @mcp.prompt()
    def get_incident(sys_id: str) -> str:
        """Prepare a request to retrieve an incident by sys_id."""
        return (
            f"Use the get_record tool to retrieve the incident with sys_id '{sys_id}' "
            "and return its number, short_description, state, and priority."
        )
