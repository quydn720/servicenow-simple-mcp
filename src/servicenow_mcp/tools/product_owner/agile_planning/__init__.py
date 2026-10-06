from fastmcp import FastMCP

from servicenow_mcp.tools import ClientFactory
from . import epics, products, stories


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    stories.register(mcp, client_factory)
    epics.register(mcp, client_factory)
    products.register(mcp, client_factory)
