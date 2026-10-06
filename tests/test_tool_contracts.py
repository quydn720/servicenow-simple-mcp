"""Validate published contracts and their enforcement over the MCP boundary."""

import asyncio
from unittest.mock import Mock

import pytest
import requests
from fastmcp import Client
from jsonschema import Draft202012Validator

from servicenow_mcp.servers.stdio import create_server
from servicenow_mcp.tools.contracts import DIALECT

ID = "a" * 32


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED_FEATURES", "common,service_desk,product_owner")
    monkeypatch.setattr(
        requests.Session,
        "request",
        Mock(side_effect=AssertionError("Unexpected network")),
    )
    upstream = Mock()
    upstream.get_record.return_value = {
        "sys_id": ID,
        "number": "TASK001",
        "short_description": "Summary",
        "secret_field": "private",
    }
    upstream.list_records.return_value = [upstream.get_record.return_value]
    upstream.create_record.return_value = upstream.get_record.return_value
    upstream.update_record.return_value = upstream.get_record.return_value
    factory = Mock(return_value=upstream)
    return create_server(factory), factory, upstream


def test_all_discovered_contracts_are_explicit_and_self_contained(server):
    mcp, factory, _ = server

    async def run():
        async with Client(mcp, mode="legacy") as connection:
            tools = await connection.list_tools()
            assert len(tools) == 15
            for tool in tools:
                assert tool.input_schema["$schema"] == DIALECT
                assert tool.input_schema["additionalProperties"] is False
                for prop in tool.input_schema["properties"].values():
                    assert prop["description"]
                assert tool.output_schema["$schema"] == DIALECT
                assert tool.output_schema != {
                    "type": "object",
                    "additionalProperties": True,
                }
                for schema in (tool.input_schema, tool.output_schema):
                    Draft202012Validator.check_schema(schema)

                    # Publication must not require resolving external definitions.
                    def check(node):
                        if isinstance(node, dict):
                            if "$ref" in node:
                                assert node["$ref"].startswith("#")
                            for value in node.values():
                                check(value)
                        elif isinstance(node, list):
                            for value in node:
                                check(value)

                    check(schema)

    asyncio.run(run())
    factory.assert_not_called()


@pytest.mark.parametrize(
    "name,args",
    [
        ("get_record", {"table": "incident", "sys_id": "bad-id"}),
        ("get_record", {"table": "incident", "sys_id": ID, "fields": ["secret_field"]}),
        ("get_record", {"table": "sys_user", "sys_id": ID}),
        ("list_records", {"table": "incident", "fields": []}),
        ("list_records", {"table": "incident", "fields": ["sys_id", "sys_id"]}),
        ("list_records", {"table": "incident", "limit": 0}),
        ("list_records", {"table": "incident", "limit": 101}),
        ("list_records", {"table": "incident", "limit": "5"}),
        ("list_records", {"table": "incident", "limit": True}),
        ("list_agile_stories", {"fields": ["name"]}),
        ("list_agile_epics", {"limit": -1}),
        ("list_agile_products", {"fields": ["short_description"]}),
        ("create_task", {"short_description": " ", "priority": "3"}),
        ("create_task", {"short_description": "x" * 161}),
        ("create_task", {"short_description": "x", "priority": "99"}),
        ("create_task", {"short_description": "x", "priority": 3}),
        ("create_task", {"short_description": "x", "assignment_group": "bad-id"}),
        ("create_task", {"short_description": "x", "description": "x" * 4001}),
        ("create_task", {"short_description": "x", "unexpected": True}),
        ("create_incident", {"short_description": None}),
        ("create_agile_story", {"short_description": "x", "story_points": 101}),
        ("create_agile_story", {"short_description": "x", "story_points": True}),
        ("create_agile_story", {"short_description": "x", "epic": ""}),
        (
            "create_agile_story",
            {"short_description": "x", "acceptance_criteria": "x" * 4001},
        ),
        ("create_agile_epic", {"short_description": "x", "priority": "6"}),
        ("update_agile_story", {"sys_id": ID, "product": "bad-id"}),
        ("update_agile_epic", {"sys_id": ID, "priority": "0"}),
        ("confirm_pending_write", {"preview_id": "x", "confirmed": "true"}),
        ("confirm_pending_write", {"preview_id": "", "confirmed": True}),
        (
            "confirm_pending_write",
            {"preview_id": "x", "confirmed": True, "fields": {"priority": "1"}},
        ),
    ],
)
def test_invalid_arguments_never_create_client(server, name, args):
    mcp, factory, _ = server

    async def run():
        async with Client(mcp, mode="legacy") as connection:
            result = await connection.call_tool(name, args, raise_on_error=False)
            assert result.is_error is True

    asyncio.run(run())
    factory.assert_not_called()


@pytest.mark.parametrize(
    "name,args",
    [
        ("get_record", {"table": "incident", "sys_id": ID, "fields": ["number"]}),
        ("list_records", {"table": "incident", "fields": ["number"], "limit": 1}),
        ("get_agile_story", {"sys_id": ID, "fields": ["number"]}),
        ("list_agile_stories", {"fields": ["number"], "limit": 1}),
        ("get_agile_epic", {"sys_id": ID, "fields": ["number"]}),
        ("list_agile_epics", {"fields": ["number"], "limit": 1}),
        ("get_agile_product", {"sys_id": ID, "fields": ["sys_id"]}),
        ("list_agile_products", {"fields": ["sys_id"], "limit": 1}),
    ],
)
def test_read_results_match_schema_and_project_requested_fields(server, name, args):
    mcp, _, upstream = server

    async def run():
        async with Client(mcp, mode="legacy") as connection:
            tool = next(t for t in await connection.list_tools() if t.name == name)
            result = await connection.call_tool(name, args)
            data = result.structured_content
            Draft202012Validator(tool.output_schema).validate(data)
            record = data["record"] if "record" in data else data["records"][0]
            assert set(record) == {"sys_id", *args["fields"]}
            assert "secret_field" not in str(data)
            if "records" in data:
                assert data["count"] == len(data["records"])

    asyncio.run(run())
    method = upstream.get_record if name.startswith("get_") else upstream.list_records
    assert "sys_id" in method.call_args.kwargs["fields"]


@pytest.mark.parametrize(
    "name,args",
    [
        ("create_incident", {"short_description": " x "}),
        ("create_task", {"short_description": " x "}),
        ("create_agile_story", {"short_description": " x ", "story_points": 0}),
        ("create_agile_epic", {"short_description": " x "}),
        ("update_agile_story", {"sys_id": ID, "epic": "", "description": ""}),
        ("update_agile_epic", {"sys_id": ID, "product": ""}),
    ],
)
def test_preview_and_confirmation_variants_match_schemas(server, name, args):
    mcp, factory, _ = server

    async def run():
        async with Client(mcp, mode="legacy") as connection:
            tools = {t.name: t for t in await connection.list_tools()}
            for approved in (False, True):
                pending = (await connection.call_tool(name, args)).structured_content
                Draft202012Validator(tools[name].output_schema).validate(pending)
                if "short_description" in args:
                    assert pending["preview"]["fields"]["short_description"] == "x"
                    if name != "create_incident":
                        assert pending["preview"]["fields"]["priority"] == "3"
                if not approved:
                    factory.assert_not_called()
                finished = (
                    await connection.call_tool(
                        "confirm_pending_write",
                        {
                            "preview_id": pending["preview_id"],
                            "confirmed": approved,
                        },
                    )
                ).structured_content
                Draft202012Validator(
                    tools["confirm_pending_write"].output_schema
                ).validate(finished)
                if approved:
                    assert "secret_field" not in str(finished)
                else:
                    assert finished["status"] == "cancelled"

    asyncio.run(run())


@pytest.mark.parametrize(
    "record", [{"sys_id": "bad-id"}, {"sys_id": ID, "number": 42}, {}]
)
def test_malformed_upstream_record_is_not_a_success(server, record):
    mcp, _, upstream = server
    upstream.get_record.return_value = record

    async def run():
        async with Client(mcp, mode="legacy") as connection:
            result = await connection.call_tool(
                "get_record", {"table": "incident", "sys_id": ID}, raise_on_error=False
            )
            assert result.is_error is True

    asyncio.run(run())


def test_excessive_upstream_collection_is_not_a_success(server):
    mcp, _, upstream = server
    upstream.list_records.return_value = [{"sys_id": ID}, {"sys_id": ID}]

    async def run():
        async with Client(mcp, mode="legacy") as connection:
            result = await connection.call_tool(
                "list_records", {"table": "incident", "limit": 1}, raise_on_error=False
            )
            assert result.is_error is True

    asyncio.run(run())


def test_normalization_and_inclusive_write_boundaries(server):
    mcp, factory, _ = server

    async def run():
        async with Client(mcp, mode="legacy") as connection:
            result = await connection.call_tool(
                "create_agile_story",
                {
                    "short_description": " " + "x" * 160 + " ",
                    "description": " " + "d" * 4000 + " ",
                    "acceptance_criteria": "",
                    "story_points": 100,
                    "priority": "5",
                    "product": ID.upper(),
                },
            )
            payload = result.structured_content["preview"]["fields"]
            assert payload == {
                "short_description": "x" * 160,
                "description": "d" * 4000,
                "acceptance_criteria": "",
                "story_points": 100,
                "priority": "5",
                "product": ID.upper(),
            }

    asyncio.run(run())
    factory.assert_not_called()


def test_invalid_persisted_write_result_consumes_preview_and_matches_error_schema(
    server,
):
    mcp, _, upstream = server
    upstream.create_record.return_value = {"sys_id": "bad-id"}

    async def run():
        async with Client(mcp, mode="legacy") as connection:
            tools = {t.name: t for t in await connection.list_tools()}
            pending = (
                await connection.call_tool("create_task", {"short_description": "x"})
            ).structured_content
            args = {"preview_id": pending["preview_id"], "confirmed": True}
            failed = (
                await connection.call_tool("confirm_pending_write", args)
            ).structured_content
            Draft202012Validator(tools["confirm_pending_write"].output_schema).validate(
                failed
            )
            assert failed["status"] == "error"
            assert "may already have committed" in failed["retry_guidance"]
            again = (
                await connection.call_tool("confirm_pending_write", args)
            ).structured_content
            Draft202012Validator(tools["confirm_pending_write"].output_schema).validate(
                again
            )
            assert again["status"] == "error"

    asyncio.run(run())
    upstream.create_record.assert_called_once()
