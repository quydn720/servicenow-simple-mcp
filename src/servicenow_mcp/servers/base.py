"""Project protocol errors and safe server-side tool-request logging."""

import logging

from fastmcp import FastMCP
from mcp import types
from mcp.shared.exceptions import MCPError

from servicenow_mcp.observability.metrics import record_tool_call


class _ToolRequestLogFilter(logging.Filter):
    def filter(self, record):
        if record.funcName == "_on_call_tool":
            # FastMCP's DEBUG handler otherwise includes every raw argument.
            record.msg = "MCP tools/call received (arguments omitted)."
            record.args = ()
        return True


class ErrorReportingServer(FastMCP):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        logger = logging.getLogger("fastmcp.server.mixins.mcp_operations")
        if not any(isinstance(f, _ToolRequestLogFilter) for f in logger.filters):
            logger.addFilter(_ToolRequestLogFilter())

    async def _on_call_tool(self, ctx, params):
        try:
            result = await super()._on_call_tool(ctx, params)
        except Exception:
            record_tool_call("unknown", "error", "PROTOCOL_ERROR")
            raise
        # FastMCP 4.0.5 returns an unstructured tool result for unknown tools.
        # Keep genuine execution errors in results, but use JSON-RPC for lookup
        # failures as required by the project standard. Do not echo the name.
        if (
            isinstance(result, types.CallToolResult)
            and result.is_error
            and result.structured_content is None
            and any(
                block.type == "text" and block.text.startswith("Unknown tool:")
                for block in result.content
            )
        ):
            record_tool_call("unknown", "error", "UNKNOWN_TOOL")
            raise MCPError(code=-32602, message="Unknown or unavailable tool.")
        if isinstance(result, types.CallToolResult) and result.is_error:
            code = (result.structured_content or {}).get("code", "")
            record_tool_call(params.name, "error", code if isinstance(code, str) else "")
        else:
            record_tool_call(params.name, "success")
        return result
