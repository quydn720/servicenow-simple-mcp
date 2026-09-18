from fastmcp import FastMCP
from app.tools import ClientFactory
from . import stories


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    stories.register(mcp, client_factory)
