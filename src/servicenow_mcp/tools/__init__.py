from typing import Callable

from servicenow_mcp.client import ServiceNowClient

ClientFactory = Callable[[], ServiceNowClient]
