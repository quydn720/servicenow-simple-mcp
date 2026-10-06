"""Service-desk workflows across the real MCP boundary, without live calls."""

import asyncio
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from fastmcp import Client
from jsonschema import Draft202012Validator

from servicenow_mcp.errors import OperationError
from servicenow_mcp.servers.stdio import create_server
from servicenow_mcp.tools.contracts import (
    COMMON_FIELDS,
    KNOWLEDGE_FIELDS,
    CHANGE_STATUS_FIELDS,
)

ID = "a" * 32
NEW_TOOLS = {
    "list_incidents",
    "get_incident",
    "list_knowledge_articles",
    "update_incident_journal",
    "get_change_status",
}


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED_FEATURES", "service_desk")
    monkeypatch.setattr(
        requests.Session,
        "request",
        Mock(side_effect=AssertionError("Live calls forbidden")),
    )
    upstream = Mock()
    upstream.list_records.return_value = [
        {"sys_id": ID, "short_description": "VPN", "private": "secret"}
    ]
    upstream.get_record.return_value = {
        "sys_id": ID,
        "state": "-1",
        "approval": "requested",
        "private": "secret",
    }
    upstream.update_record.return_value = {
        "sys_id": ID,
        "number": "INC0001",
        "private": "secret",
    }
    factory = Mock(return_value=upstream)
    return create_server(factory), factory, upstream


async def checked_call(connection, name, args):
    tools = {t.name: t for t in await connection.list_tools()}
    result = await connection.call_tool(name, args, raise_on_error=False)
    Draft202012Validator(tools[name].output_schema).validate(result.structured_content)
    return result


def test_new_contracts_match_versioned_snapshots(setup):
    server, factory, _ = setup

    async def run():
        async with Client(server, mode="legacy") as connection:
            tools = {t.name: t for t in await connection.list_tools()}
            for name in NEW_TOOLS:
                folder = (
                    Path(__file__).resolve().parents[1]
                    / "docs"
                    / "tool-contracts"
                    / name
                    / "1.0.0"
                )
                for kind, schema in (
                    ("input", tools[name].input_schema),
                    ("output", tools[name].output_schema),
                ):
                    assert (
                        json.loads((folder / f"{kind}.schema.json").read_text())
                        == schema
                    )
            for name, args in (
                ("list_incidents", {}),
                ("list_incidents", {"search_text": None}),
                ("update_incident_journal", {"sys_id": ID}),
                ("update_incident_journal", {"sys_id": ID, "comments": None}),
            ):
                assert not Draft202012Validator(tools[name].input_schema).is_valid(args)

    asyncio.run(run())
    factory.assert_not_called()


@pytest.mark.parametrize(
    "name,args,query,table,fields",
    [
        (
            "list_incidents",
            {"search_text": " VPN "},
            "short_descriptionLIKEVPN",
            "incident",
            COMMON_FIELDS,
        ),
        (
            "list_incidents",
            {"number": "INC0001"},
            "number=INC0001",
            "incident",
            COMMON_FIELDS,
        ),
        (
            "list_incidents",
            {"search_text": "VPN", "number": "INC0001"},
            "number=INC0001^short_descriptionLIKEVPN",
            "incident",
            COMMON_FIELDS,
        ),
        (
            "list_knowledge_articles",
            {"search_text": "VPN", "knowledge_base": ID},
            "active=true^workflow_state=published^short_descriptionLIKEVPN^kb_knowledge_base="
            + ID,
            "kb_knowledge",
            KNOWLEDGE_FIELDS,
        ),
        (
            "list_knowledge_articles",
            {"search_text": "VPN"},
            "active=true^workflow_state=published^short_descriptionLIKEVPN",
            "kb_knowledge",
            KNOWLEDGE_FIELDS,
        ),
    ],
)
def test_search_builds_only_validated_internal_queries(
    setup, name, args, query, table, fields
):
    server, _, upstream = setup

    async def run():
        async with Client(server, mode="legacy") as connection:
            result = await checked_call(connection, name, args)
            assert not result.is_error
            assert result.structured_content["count"] == 1
            assert "private" not in str(result.structured_content)

    asyncio.run(run())
    upstream.list_records.assert_called_once_with(
        table, query=query, fields=list(fields), limit=10
    )
    upstream.create_record.assert_not_called()
    upstream.update_record.assert_not_called()


@pytest.mark.parametrize(
    "name,args",
    [
        ("list_incidents", {}),
        ("list_incidents", {"search_text": None, "number": None}),
        ("list_incidents", {"number": "INC1^ORactive=true"}),
        ("list_incidents", {"number": "inc0001"}),
        ("list_incidents", {"search_text": "VPN", "query": "active=true"}),
        ("list_incidents", {"search_text": "VPN", "limit": 101}),
        ("list_incidents", {"search_text": "VPN", "limit": True}),
        ("list_knowledge_articles", {"search_text": "VPN", "knowledge_base": "bad"}),
        ("list_knowledge_articles", {"search_text": "VPN", "fields": ["text"]}),
        ("get_incident", {"sys_id": "bad"}),
        ("get_change_status", {"sys_id": "bad"}),
        ("update_incident_journal", {"sys_id": ID}),
        (
            "update_incident_journal",
            {"sys_id": ID, "work_notes": None, "comments": None},
        ),
        ("update_incident_journal", {"sys_id": ID, "work_notes": " "}),
        ("update_incident_journal", {"sys_id": ID, "comments": "x" * 4001}),
        ("update_incident_journal", {"sys_id": "bad", "comments": "Note"}),
        ("update_incident_journal", {"sys_id": ID, "state": "2"}),
    ],
)
def test_invalid_inputs_never_create_client(setup, name, args):
    server, factory, _ = setup

    async def run():
        async with Client(server, mode="legacy") as connection:
            result = await checked_call(connection, name, args)
            assert result.is_error
            assert result.structured_content["code"] == "VALIDATION_ERROR"
            assert result.structured_content["outcome"] == "not_attempted"

    asyncio.run(run())
    factory.assert_not_called()


@pytest.mark.parametrize("name", ["list_incidents", "list_knowledge_articles"])
@pytest.mark.parametrize(
    "text",
    [
        "VPN^ORactive=true",
        "javascript:gs.getUserID()",
        "JavaScript :alert(1)",
        "VPN\nORDERBYnumber",
        "\tVPN",
        "",
        " ",
        "x" * 161,
    ],
)
def test_query_syntax_and_invalid_search_text_are_rejected(setup, name, text):
    test_invalid_inputs_never_create_client(setup, name, {"search_text": text})


@pytest.mark.parametrize(
    "name,fields",
    [("get_incident", COMMON_FIELDS), ("get_change_status", CHANGE_STATUS_FIELDS)],
)
def test_details_and_status_are_narrow_read_only_results(setup, name, fields):
    server, _, upstream = setup

    async def run():
        async with Client(server, mode="legacy") as connection:
            result = await checked_call(connection, name, {"sys_id": ID})
            assert not result.is_error
            data = result.structured_content
            assert data["record"]["state"] == "-1"
            assert "private" not in str(data)
            if name == "get_change_status":
                assert data["record"]["approval"] == "requested"

    asyncio.run(run())
    table = "incident" if name == "get_incident" else "change_request"
    upstream.get_record.assert_called_once_with(table, ID, fields=list(fields))
    upstream.update_record.assert_not_called()


@pytest.mark.parametrize("name", ["get_incident", "get_change_status"])
@pytest.mark.parametrize(
    "record", [{}, {"sys_id": "b" * 32}, {"sys_id": ID, "state": 1}]
)
def test_invalid_upstream_records_are_safe_errors(setup, name, record):
    server, _, upstream = setup
    upstream.get_record.return_value = record

    async def run():
        async with Client(server, mode="legacy") as connection:
            result = await checked_call(connection, name, {"sys_id": ID})
            assert result.is_error
            assert result.structured_content["code"] == "UPSTREAM_ERROR"

    asyncio.run(run())


@pytest.mark.parametrize(
    "fields",
    [
        {"work_notes": " Internal note "},
        {"comments": " Customer comment "},
        {"work_notes": " Note ", "comments": " Comment "},
    ],
)
@pytest.mark.parametrize("approve", [False, True])
def test_journals_preview_exact_payload_cancel_and_replay(setup, fields, approve):
    server, factory, upstream = setup

    async def run():
        async with Client(server, mode="legacy") as connection:
            pending = await checked_call(
                connection, "update_incident_journal", {"sys_id": ID, **fields}
            )
            assert not pending.is_error
            data = pending.structured_content
            assert data["preview"] == {
                "operation": "update",
                "table": "incident",
                "sys_id": ID,
                "fields": {key: value.strip() for key, value in fields.items()},
            }
            factory.assert_not_called()
            args = {"preview_id": data["preview_id"], "confirmed": approve}
            result = await checked_call(connection, "confirm_pending_write", args)
            assert not result.is_error
            if approve:
                upstream.update_record.assert_called_once_with(
                    "incident", ID, data["preview"]["fields"]
                )
            else:
                assert result.structured_content["status"] == "cancelled"
                factory.assert_not_called()
            replay = await checked_call(connection, "confirm_pending_write", args)
            assert replay.is_error
            assert replay.structured_content["code"] == "CONFIRMATION_INVALID"
            upstream.create_record.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize(
    "code,outcome", [("PERMISSION_DENIED", "failed"), ("TIMEOUT", "unknown")]
)
def test_journal_write_failure_is_not_retried(setup, code, outcome):
    server, _, upstream = setup
    upstream.update_record.side_effect = OperationError(code, outcome=outcome)

    async def run():
        async with Client(server, mode="legacy") as connection:
            pending = await checked_call(
                connection,
                "update_incident_journal",
                {"sys_id": ID, "comments": "Comment"},
            )
            args = {
                "preview_id": pending.structured_content["preview_id"],
                "confirmed": True,
            }
            result = await checked_call(connection, "confirm_pending_write", args)
            assert result.is_error
            data = result.structured_content
            assert data["code"] == code and data["outcome"] == outcome
            assert data["retryable"] is False
            assert data["preview"]["fields"] == {"comments": "Comment"}
            assert (
                await checked_call(connection, "confirm_pending_write", args)
            ).is_error

    asyncio.run(run())
    upstream.update_record.assert_called_once()
