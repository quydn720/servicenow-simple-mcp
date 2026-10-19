"""Service-desk workflows across the real MCP boundary, without live calls."""

import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from fastmcp import Client
from jsonschema import Draft202012Validator

from servicenow_mcp.errors import OperationError
from servicenow_mcp.servers.stdio import create_server
from servicenow_mcp.tools.contracts import (
    INCIDENT_SEARCH_FIELDS,
    INCIDENT_DETAIL_FIELDS,
    KNOWLEDGE_FIELDS,
    CHANGE_STATUS_FIELDS,
)

ID = "a" * 32
NEW_TOOLS = {
    "list_incidents",
    "get_incident",
    "get_incident_v3",
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
    upstream.instance_url = "https://example.test"
    upstream.list_records.return_value = [
        {
            "sys_id": ID,
            "number": "INC0001",
            "short_description": "VPN",
            "private": "secret",
        }
    ]
    upstream.get_record.return_value = {
        "sys_id": ID,
        "number": "INC0001",
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
                version = {
                    "list_incidents": "2.0.0",
                    "get_incident": "2.0.0",
                    "get_incident_v3": "3.0.0",
                }.get(name, "1.0.0")
                folder = (
                    Path(__file__).resolve().parents[1]
                    / "docs"
                    / "tool-contracts"
                    / name
                    / version
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
            INCIDENT_SEARCH_FIELDS,
        ),
        (
            "list_incidents",
            {"number": "INC0001"},
            "number=INC0001",
            "incident",
            INCIDENT_SEARCH_FIELDS,
        ),
        (
            "list_incidents",
            {"search_text": "VPN", "number": "INC0001"},
            "number=INC0001^short_descriptionLIKEVPN",
            "incident",
            INCIDENT_SEARCH_FIELDS,
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
    if name == "list_incidents":
        upstream.list_records.assert_called_once_with(
            table,
            query=query,
            fields=list(fields),
            limit=10,
            offset=0,
            order_by=["ORDERBYDESCsys_updated_on", "ORDERBYsys_id"],
        )
    else:
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
        ("list_incidents", {"state": "Open^ORactive=true"}),
        ("list_incidents", {"caller_id": "bad"}),
        ("list_incidents", {"updated_after": "2026-10-02T00:00:00+07:00"}),
        (
            "list_incidents",
            {
                "updated_after": "2026-10-02T00:00:00Z",
                "updated_before": "2026-10-01T00:00:00Z",
            },
        ),
        ("list_incidents", {"number": "INC0001", "offset": 100001}),
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
    [("get_incident", ["sys_id", *INCIDENT_DETAIL_FIELDS]), ("get_change_status", CHANGE_STATUS_FIELDS)],
)
def test_details_and_status_are_narrow_read_only_results(setup, name, fields):
    server, _, upstream = setup

    async def run():
        async with Client(server, mode="legacy") as connection:
            result = await checked_call(connection, name, {"sys_id": ID})
            assert not result.is_error
            data = result.structured_content
            assert data["record"]["state"] == "-1"
            if name == "get_incident":
                assert "sys_id" not in data and "sys_id" not in data["record"]
            assert "private" not in str(data)
            if name == "get_change_status":
                assert data["record"]["approval"] == "requested"

    asyncio.run(run())
    table = "incident" if name == "get_incident" else "change_request"
    upstream.get_record.assert_called_once_with(table, ID, fields=list(fields))
    upstream.update_record.assert_not_called()


def test_incident_filters_pagination_display_values_and_safe_audit(setup, caplog):
    server, _, upstream = setup
    caplog.set_level(logging.INFO, logger="servicenow_mcp.tools.service_desk.incidents")
    upstream.list_records.return_value = [
        {
            "sys_id": ID,
            "number": "INC0001",
            "short_description": "VPN",
            "state": "Open",
            "priority": "Low - 4",
            "sys_updated_on": "2026-10-06 07:00:00",
        }
    ]

    async def run():
        async with Client(server, mode="legacy") as connection:
            result = await checked_call(
                connection,
                "list_incidents",
                {
                    "number": "INC0001",
                    "search_text": "VPN",
                    "state": "Open",
                    "assignment_group": "b" * 32,
                    "caller_id": "c" * 32,
                    "updated_after": "2026-10-01T00:00:00Z",
                    "updated_before": "2026-10-07T00:00:00Z",
                    "limit": 1,
                    "offset": 10,
                },
            )
            data = result.structured_content
            assert data["count"] == 1
            assert data["next_offset"] == 11
            assert data["records"] == [
                {
                    "number": "INC0001",
                    "url": "https://example.test/incident_list.do?sysparm_query=number%3DINC0001",
                    "short_description": "VPN",
                    "state": "Open",
                    "priority": "Low - 4",
                    "sys_updated_on": "2026-10-06 07:00:00",
                }
            ]

    asyncio.run(run())
    upstream.list_records.assert_called_once_with(
        "incident",
        query="number=INC0001^short_descriptionLIKEVPN^state=Open^assignment_group="
        + "b" * 32
        + "^caller_id="
        + "c" * 32
        + "^sys_updated_on>=2026-10-01 00:00:00^sys_updated_on<2026-10-07 00:00:00",
        fields=list(INCIDENT_SEARCH_FIELDS),
        limit=1,
        offset=10,
        order_by=["ORDERBYDESCsys_updated_on", "ORDERBYsys_id"],
    )
    audit = [record.incident_search_audit for record in caplog.records if hasattr(record, "incident_search_audit")]
    assert audit
    assert audit[-1]["outcome"] == "success"
    assert audit[-1]["result_count"] == 1
    assert "VPN" not in str(audit[-1]) and ID not in str(audit[-1])


def test_incident_detail_can_be_retrieved_by_number_without_sys_id(setup):
    server, _, upstream = setup
    upstream.list_records.return_value = [
        {"sys_id": ID, "number": "INC0001", "state": "Open", "priority": "Low - 4"}
    ]

    async def run():
        async with Client(server, mode="legacy") as connection:
            result = await checked_call(connection, "get_incident", {"number": "INC0001"})
            assert result.structured_content == {
                "table": "incident",
                "record": {
                    "number": "INC0001",
                    "url": "https://example.test/incident_list.do?sysparm_query=number%3DINC0001",
                    "state": "Open",
                    "priority": "Low - 4",
                },
            }

    asyncio.run(run())
    upstream.list_records.assert_called_once_with(
        "incident", query="number=INC0001", fields=list(INCIDENT_DETAIL_FIELDS), limit=1
    )


def test_incident_v3_number_lookup_reports_exclusions_without_values(setup, caplog):
    server, _, upstream = setup
    upstream.list_records.return_value = [
        {
            "sys_id": ID,
            "number": "INC0001",
            "short_description": "VPN",
            "private": "private-value",
            "work_notes": "internal-note",
            "comments": "customer-comment",
            "attachment": "attachment-value",
        }
    ]
    caplog.set_level(logging.INFO, logger="servicenow_mcp.tools.service_desk.incidents")

    async def run():
        async with Client(server, mode="legacy") as connection:
            result = await checked_call(
                connection, "get_incident_v3", {"number": "INC0001"}
            )
            assert not result.is_error
            data = result.structured_content
            assert data["record"] == {
                "number": "INC0001",
                "url": "https://example.test/incident_list.do?sysparm_query=number%3DINC0001",
                "short_description": "VPN",
            }
            assert data["redaction"] == {
                "excluded_categories": [
                    "journal_history",
                    "attachments",
                    "non_allowlisted_fields",
                ],
                "omitted_fields": [
                    field
                    for field in INCIDENT_DETAIL_FIELDS
                    if field not in {"number", "short_description"}
                ],
            }
            assert not any(
                secret in str(data)
                for secret in (ID, "private-value", "internal-note", "customer-comment", "attachment-value")
            )

    asyncio.run(run())
    upstream.list_records.assert_called_once_with(
        "incident", query="number=INC0001", fields=list(INCIDENT_DETAIL_FIELDS), limit=2
    )
    audit = [record.incident_detail_audit for record in caplog.records if hasattr(record, "incident_detail_audit")]
    assert audit[-1] == {
        "event": "incident_detail_retrieval",
        "tool": "get_incident_v3",
        "tool_version": "3.0.0",
        "operation": "read",
        "identity": "unavailable",
        "outcome": "success",
    }
    assert all(value not in str(audit[-1]) for value in (ID, "INC0001", "VPN"))


def test_incident_v3_sys_id_lookup_uses_fixed_allowlist(setup):
    server, _, upstream = setup
    upstream.get_record.return_value = {
        "sys_id": ID,
        "number": "INC0001",
        "state": "Open",
        "work_notes": "internal-note",
        "private": "private-value",
    }

    async def run():
        async with Client(server, mode="legacy") as connection:
            result = await checked_call(connection, "get_incident_v3", {"sys_id": ID})
            assert result.structured_content["record"]["state"] == "Open"
            assert "sys_id" not in str(result.structured_content)
            assert "internal-note" not in str(result.structured_content)
            assert "private-value" not in str(result.structured_content)

    asyncio.run(run())
    upstream.get_record.assert_called_once_with(
        "incident", ID, fields=["sys_id", *INCIDENT_DETAIL_FIELDS]
    )


@pytest.mark.parametrize(
    "records,code",
    [
        ([], "NOT_FOUND"),
        (None, "UPSTREAM_ERROR"),
        ([None], "UPSTREAM_ERROR"),
        ([{"number": "INC0002"}], "UPSTREAM_ERROR"),
        ([{"number": "INC0001"}, {"number": "INC0001"}], "UPSTREAM_ERROR"),
    ],
)
def test_incident_v3_number_lookup_handles_missing_or_ambiguous_results(setup, records, code):
    server, _, upstream = setup
    upstream.list_records.return_value = records

    async def run():
        async with Client(server, mode="legacy") as connection:
            result = await checked_call(
                connection, "get_incident_v3", {"number": "INC0001"}
            )
            assert result.is_error
            assert result.structured_content["code"] == code
            assert "INC0001" not in str(result.structured_content)

    asyncio.run(run())


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"sys_id": None, "number": None},
        {"sys_id": ID, "number": "INC0001"},
        {"sys_id": "invalid"},
        {"number": "inc0001"},
    ],
)
def test_incident_v3_invalid_identifiers_fail_before_client_creation(setup, args):
    server, factory, _ = setup

    async def run():
        async with Client(server, mode="legacy") as connection:
            result = await checked_call(connection, "get_incident_v3", args)
            assert result.is_error
            assert result.structured_content["code"] == "VALIDATION_ERROR"
            assert result.structured_content["outcome"] == "not_attempted"

    asyncio.run(run())
    factory.assert_not_called()


def test_incident_v3_permission_denial_is_audited_without_identifier(setup, caplog):
    server, _, upstream = setup
    upstream.list_records.side_effect = OperationError(
        "PERMISSION_DENIED", outcome="failed"
    )
    caplog.set_level(logging.INFO, logger="servicenow_mcp.tools.service_desk.incidents")

    async def run():
        async with Client(server, mode="legacy") as connection:
            result = await checked_call(
                connection, "get_incident_v3", {"number": "INC0001"}
            )
            assert result.is_error
            assert result.structured_content["code"] == "PERMISSION_DENIED"

    asyncio.run(run())
    audit = [
        record.incident_detail_audit
        for record in caplog.records
        if hasattr(record, "incident_detail_audit")
    ]
    assert audit[-1]["outcome"] == "error"
    assert audit[-1]["error_code"] == "PERMISSION_DENIED"
    assert all(value not in str(audit[-1]) for value in (ID, "INC0001"))


def test_incident_search_denial_is_audited_without_filter_values(setup, caplog):
    server, _, upstream = setup
    caplog.set_level(logging.INFO, logger="servicenow_mcp.tools.service_desk.incidents")
    upstream.list_records.side_effect = OperationError("PERMISSION_DENIED", outcome="failed")

    async def run():
        async with Client(server, mode="legacy") as connection:
            result = await checked_call(
                connection, "list_incidents", {"number": "INC0001"}
            )
            assert result.is_error
            assert result.structured_content["code"] == "PERMISSION_DENIED"

    asyncio.run(run())
    audit = [
        record.incident_search_audit
        for record in caplog.records
        if hasattr(record, "incident_search_audit")
    ]
    assert audit[-1]["outcome"] == "error"
    assert audit[-1]["error_code"] == "PERMISSION_DENIED"
    assert "INC0001" not in str(audit[-1])


@pytest.mark.parametrize("name", ["get_incident", "get_incident_v3", "get_change_status"])
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
