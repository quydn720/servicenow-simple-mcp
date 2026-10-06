from fastmcp import FastMCP

from servicenow_mcp.config.local import enabled_features
from servicenow_mcp.tools import ClientFactory, common, service_desk, product_owner, developer
from servicenow_mcp.tools.write_review import register_write_review

REGISTRY = {
    "common": common.register,
    "service_desk": service_desk.register,
    "product_owner": product_owner.register,
    "developer": developer.register,
}


def register_tools(mcp: FastMCP, client_factory: ClientFactory) -> None:
    features = enabled_features()
    if {"service_desk", "product_owner"}.intersection(features):
        register_write_review(mcp)
    for feature in features:
        REGISTRY[feature](mcp, client_factory)
