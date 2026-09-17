import asyncio
import importlib


def test_server_imports_without_service_now_env(monkeypatch):
    monkeypatch.delenv("SERVICENOW_INSTANCE", raising=False)
    monkeypatch.delenv("SERVICENOW_USERNAME", raising=False)
    monkeypatch.delenv("SERVICENOW_PASSWORD", raising=False)

    import app.server as server_module
    importlib.reload(server_module)

    tools = asyncio.run(server_module.mcp.list_tools())
    assert any(tool.name == "list_records" for tool in tools)
    assert any(tool.name == "get_record" for tool in tools)
    assert any(tool.name == "create_task" for tool in tools)
