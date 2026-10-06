from fastmcp import FastMCP
from servicenow_mcp.tools import ClientFactory
from .shared import register_reads


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    register_reads(mcp, client_factory, "product", "products", "cmdb_model", ["sys_id", "name"])
