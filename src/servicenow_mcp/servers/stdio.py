from __future__ import annotations

from fastmcp import FastMCP

from servicenow_mcp.config.local import Settings
from servicenow_mcp.config.environment import load_environment
from servicenow_mcp.client import ServiceNowClient
from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.tools.registry import register_tools
from servicenow_mcp.tools.write_review import WRITE_INSTRUCTIONS


def get_client() -> ServiceNowClient:
    return ServiceNowClient(Settings.from_env())


def create_server(client_factory: ClientFactory = get_client) -> FastMCP:
    server = FastMCP("servicenow-pdi", instructions=WRITE_INSTRUCTIONS)
    register_tools(server, client_factory)
    return server


def main() -> None:
    load_environment()
    create_server().run()


if __name__ == "__main__":
    main()
