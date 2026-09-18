from fastmcp import FastMCP

from app.config import enabled_features
from app.tools import ClientFactory, common, service_desk, product_owner, developer

REGISTRY = {
    "common": common.register,
    "service_desk": service_desk.register,
    "product_owner": product_owner.register,
    "developer": developer.register,
}


def register_tools(mcp: FastMCP, client_factory: ClientFactory) -> None:
    for feature in enabled_features():
        REGISTRY[feature](mcp, client_factory)
