import asyncio
import importlib
from unittest.mock import Mock


def test_server_imports_without_service_now_env(monkeypatch):
    monkeypatch.delenv("SERVICENOW_INSTANCE", raising=False)
    monkeypatch.delenv("SERVICENOW_USERNAME", raising=False)
    monkeypatch.delenv("SERVICENOW_PASSWORD", raising=False)

    import servicenow_mcp.servers.stdio as server_module
    importlib.reload(server_module)

    tools = asyncio.run(server_module.create_server().list_tools())
    assert any(tool.name == "list_records" for tool in tools)
    assert any(tool.name == "get_record" for tool in tools)
    assert any(tool.name == "create_task" for tool in tools)


def test_import_has_no_startup_side_effects(monkeypatch):
    import fastmcp
    from servicenow_mcp.config import environment
    from servicenow_mcp.servers import stdio

    with monkeypatch.context() as patch:
        load = Mock(side_effect=AssertionError("Environment loaded during import"))
        construct = Mock(side_effect=AssertionError("Server created during import"))
        patch.setattr(environment, "load_environment", load)
        patch.setattr(fastmcp, "FastMCP", construct)
        importlib.reload(stdio)
        load.assert_not_called()
        construct.assert_not_called()
    importlib.reload(stdio)


def test_stdio_startup_loads_environment_before_creating_server(monkeypatch):
    from servicenow_mcp.servers import stdio

    events = []
    server = Mock()
    monkeypatch.setattr(stdio, "load_environment", lambda: events.append("load"))

    def create():
        assert events == ["load"]
        return server

    monkeypatch.setattr(stdio, "create_server", create)
    stdio.main()
    server.run.assert_called_once_with()
