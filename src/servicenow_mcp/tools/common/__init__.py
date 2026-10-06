from fastmcp import FastMCP
from servicenow_mcp.tools import ClientFactory
from . import records


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    records.register(mcp, client_factory)
