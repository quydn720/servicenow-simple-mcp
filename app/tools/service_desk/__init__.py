from fastmcp import FastMCP
from app.tools import ClientFactory
from . import incidents, tasks


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    incidents.register(mcp, client_factory)
    tasks.register(mcp, client_factory)
