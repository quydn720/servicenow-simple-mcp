from fastmcp import FastMCP
from servicenow_mcp.tools import ClientFactory
from . import agile_planning


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    agile_planning.register(mcp, client_factory)
