"""Raw-query policy through real MCP calls with no ServiceNow network access."""

import asyncio
from unittest.mock import Mock

import pytest
import requests
from fastmcp import Client

from servicenow_mcp.servers.stdio import create_server


LIST_TOOLS = [
    ("list_records", {"table": "incident"}, "incident"),
    ("list_agile_stories", {}, "rm_story"),
    ("list_agile_epics", {}, "rm_epic"),
    ("list_agile_products", {}, "cmdb_model"),
]


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED_FEATURES", "common,product_owner")
    monkeypatch.setattr(
        requests.Session, "request", Mock(side_effect=AssertionError("Unexpected network")),
    )
    client = Mock()
    client.list_records.return_value = [{"sys_id": "0" * 32}]
    factory = Mock(return_value=client)
    return create_server(factory), factory, client


@pytest.mark.parametrize("name,arguments,table", LIST_TOOLS)
@pytest.mark.parametrize("query", [
    "active=true", "nameLIKEPortal", "active=true^ORpriority=1",
    "sys_id=javascript:gs.getUserID()", "", "   ",
])
def test_raw_queries_fail_before_client_creation(server, name, arguments, table, query):
    mcp, factory, client = server

    async def run():
        async with Client(mcp, mode="legacy") as connection:
            result = await connection.call_tool(
                name, {**arguments, "query": query}, raise_on_error=False,
            )
            assert result.is_error is True
            message = " ".join(c.text for c in result.content if c.type == "text")
            assert "RAW_QUERY_PROHIBITED" in message
            assert "Omit query or pass null" in message
            # Never echo caller expressions in the safe error message.
            if query.strip():
                assert query not in message

    asyncio.run(run())
    factory.assert_not_called()
    client.list_records.assert_not_called()


@pytest.mark.parametrize("name,arguments,table", LIST_TOOLS)
@pytest.mark.parametrize("extra", [{}, {"query": None}])
def test_unfiltered_lists_still_work(server, name, arguments, table, extra):
    mcp, factory, client = server

    async def run():
        async with Client(mcp, mode="legacy") as connection:
            result = await connection.call_tool(name, {
                **arguments, **extra, "fields": ["sys_id"], "limit": 5,
            })
            assert result.is_error is False
            assert result.data == {
                "table": table, "count": 1, "records": [{"sys_id": "0" * 32}],
            }

    asyncio.run(run())
    factory.assert_called_once_with()
    client.list_records.assert_called_once_with(
        table=table, query=None, fields=["sys_id"], limit=5,
    )
