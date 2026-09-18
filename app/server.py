from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from app.config import Settings
from app.service_now_client import ServiceNowClient
from app.tools import ClientFactory
from app.tools.registry import register_tools

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def get_client() -> ServiceNowClient:
    return ServiceNowClient(Settings.from_env())


def create_server(client_factory: ClientFactory = get_client) -> FastMCP:
    server = FastMCP("servicenow-pdi")
    register_tools(server, client_factory)
    return server


mcp = create_server()

if __name__ == "__main__":
    mcp.run()
