from fastmcp import FastMCP
from app.tools import ClientFactory
from . import records


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    records.register(mcp, client_factory)
