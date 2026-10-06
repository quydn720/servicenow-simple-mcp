"""Standard errors, safe output, and write uncertainty through actual MCP calls."""

import asyncio
import logging
from unittest.mock import Mock

import pytest
import requests
from fastmcp import Client
from jsonschema import Draft202012Validator

from servicenow_mcp.client import ServiceNowClient
from servicenow_mcp.config.local import Settings
from servicenow_mcp.errors import OperationError
from servicenow_mcp.servers.stdio import create_server
from servicenow_mcp.tools import write_review

ID = "a" * 32
SECRET = "sentinel-private-value"


@pytest.fixture
def upstream(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED_FEATURES", "common,service_desk,product_owner")
    monkeypatch.setattr(
        requests.Session,
        "request",
        Mock(side_effect=AssertionError("Unexpected network")),
    )
    client = ServiceNowClient(Settings("example.test", oauth_access_token=SECRET))
    client.session.request = Mock()
    return client


def validate_error(tools, name, result, code, outcome, retryable=False):
    assert result.is_error is True
    data = result.structured_content
    Draft202012Validator(tools[name].output_schema).validate(data)
    assert data["status"] == "error"
    assert data["code"] == code
    assert data["outcome"] == outcome
    assert data["retryable"] is retryable
    assert SECRET not in str(data)
    assert SECRET not in str(result.content)
    return data


@pytest.mark.parametrize(
    "name,args",
    [
        ("list_records", {"table": "incident", "limit": 0}),
        ("get_record", {"table": "incident", "sys_id": "invalid"}),
        ("create_incident", {"short_description": ""}),
        ("create_task", {"short_description": "x", "priority": "99"}),
        ("get_agile_story", {"sys_id": "invalid"}),
        ("list_agile_stories", {"limit": 0}),
        ("create_agile_story", {"short_description": ""}),
        ("update_agile_story", {"sys_id": ID}),
        ("get_agile_epic", {"sys_id": "invalid"}),
        ("list_agile_epics", {"limit": 0}),
        ("create_agile_epic", {"short_description": ""}),
        ("update_agile_epic", {"sys_id": ID}),
        ("get_agile_product", {"sys_id": "invalid"}),
        ("list_agile_products", {"limit": 0}),
        ("confirm_pending_write", {"preview_id": "unknown", "confirmed": "true"}),
        ("get_record", {"table": "incident", "sys_id": ID, SECRET: SECRET}),
    ],
)
def test_validation_errors_have_safe_schema_and_flag(upstream, name, args, caplog):
    caplog.set_level(logging.DEBUG, logger="fastmcp.server.mixins.mcp_operations")
    factory = Mock(side_effect=AssertionError("Client created during invalid call"))

    async def run():
        async with Client(create_server(factory), mode="legacy") as connection:
            tools = {t.name: t for t in await connection.list_tools()}
            result = await connection.call_tool(name, args, raise_on_error=False)
            validate_error(tools, name, result, "VALIDATION_ERROR", "not_attempted")

    asyncio.run(run())
    factory.assert_not_called()
    assert SECRET not in caplog.text


@pytest.mark.parametrize(
    "status,code,read_retryable",
    [
        (400, "UPSTREAM_ERROR", False),
        (401, "AUTHENTICATION_REQUIRED", False),
        (403, "PERMISSION_DENIED", False),
        (404, "NOT_FOUND", False),
        (408, "TIMEOUT", True),
        (429, "UPSTREAM_ERROR", True),
        (500, "UPSTREAM_ERROR", True),
        (504, "TIMEOUT", True),
    ],
)
@pytest.mark.parametrize("write", [False, True])
def test_http_failure_classification(
    upstream, status, code, read_retryable, write, caplog
):
    upstream.session.request.return_value = Mock(
        status_code=status,
        json=Mock(return_value={"error": {"message": SECRET, "detail": SECRET}}),
        text=SECRET,
        headers={"Authorization": SECRET},
    )

    async def run():
        async with Client(create_server(lambda: upstream), mode="legacy") as connection:
            tools = {t.name: t for t in await connection.list_tools()}
            if write:
                pending = (
                    await connection.call_tool(
                        "create_task", {"short_description": "x"}
                    )
                ).structured_content
                upstream.session.request.assert_not_called()
                name, args = (
                    "confirm_pending_write",
                    {"preview_id": pending["preview_id"], "confirmed": True},
                )
            else:
                name, args = "get_record", {"table": "incident", "sys_id": ID}
            result = await connection.call_tool(name, args, raise_on_error=False)
            outcome = (
                "unknown" if write and (status >= 500 or status == 408) else "failed"
            )
            data = validate_error(
                tools, name, result, code, outcome, not write and read_retryable
            )
            assert data["http_status"] == status
            if write:
                assert data["preview"] == pending["preview"]
                replay = await connection.call_tool(name, args, raise_on_error=False)
                validate_error(
                    tools, name, replay, "CONFIRMATION_INVALID", "not_attempted"
                )

    asyncio.run(run())
    upstream.session.request.assert_called_once()
    upstream.session.request.return_value.json.assert_not_called()
    assert SECRET not in caplog.text


@pytest.mark.parametrize(
    "error,code",
    [
        (requests.Timeout(SECRET), "TIMEOUT"),
        (requests.ConnectionError(SECRET), "UPSTREAM_ERROR"),
    ],
)
@pytest.mark.parametrize("write", [False, True])
def test_transport_failures_and_no_automatic_retry(
    upstream, error, code, write, caplog
):
    upstream.session.request.side_effect = error

    async def run():
        async with Client(create_server(lambda: upstream), mode="legacy") as connection:
            tools = {t.name: t for t in await connection.list_tools()}
            if write:
                pending = (
                    await connection.call_tool(
                        "create_task", {"short_description": "x"}
                    )
                ).structured_content
                name, args = (
                    "confirm_pending_write",
                    {"preview_id": pending["preview_id"], "confirmed": True},
                )
            else:
                name, args = "list_records", {"table": "incident"}
            result = await connection.call_tool(name, args, raise_on_error=False)
            data = validate_error(
                tools, name, result, code, "unknown" if write else "failed", not write
            )
            if write:
                assert "may already have committed" in data["retry_guidance"]
                replay = await connection.call_tool(name, args, raise_on_error=False)
                validate_error(
                    tools, name, replay, "CONFIRMATION_INVALID", "not_attempted"
                )

    asyncio.run(run())
    upstream.session.request.assert_called_once()
    assert SECRET not in caplog.text


@pytest.mark.parametrize(
    "error,code",
    [
        (OperationError("AUTHENTICATION_REQUIRED"), "AUTHENTICATION_REQUIRED"),
        (RuntimeError(SECRET), "INTERNAL_ERROR"),
        (TypeError(SECRET), "INTERNAL_ERROR"),
    ],
)
def test_factory_failures_are_not_attempted_and_consume_confirmed_preview(
    upstream, error, code, caplog
):
    factory = Mock(side_effect=error)

    async def run():
        async with Client(create_server(factory), mode="legacy") as connection:
            tools = {t.name: t for t in await connection.list_tools()}
            read = await connection.call_tool(
                "list_records", {"table": "incident"}, raise_on_error=False
            )
            validate_error(tools, "list_records", read, code, "not_attempted")
            pending = (
                await connection.call_tool("create_task", {"short_description": "x"})
            ).structured_content
            failed = await connection.call_tool(
                "confirm_pending_write",
                {"preview_id": pending["preview_id"], "confirmed": True},
                raise_on_error=False,
            )
            validate_error(
                tools, "confirm_pending_write", failed, code, "not_attempted"
            )

    asyncio.run(run())
    upstream.session.request.assert_not_called()
    assert SECRET not in caplog.text


def test_session_capacity_and_raw_query_codes(upstream, monkeypatch):
    async def run():
        server = create_server(lambda: upstream)
        async with Client(server, mode="legacy") as connection:
            tools = {t.name: t for t in await connection.list_tools()}
            blocked = await connection.call_tool(
                "list_records",
                {"table": "incident", "query": SECRET},
                raise_on_error=False,
            )
            validate_error(
                tools, "list_records", blocked, "RAW_QUERY_PROHIBITED", "not_attempted"
            )
            monkeypatch.setattr(write_review, "MAX_PENDING_PREVIEWS", 0)
            full = await connection.call_tool(
                "create_task", {"short_description": "x"}, raise_on_error=False
            )
            validate_error(
                tools, "create_task", full, "PREVIEW_LIMIT_EXCEEDED", "not_attempted"
            )
        async with Client(server, mode="2026-07-28") as connection:
            tools = {t.name: t for t in await connection.list_tools()}
            result = await connection.call_tool(
                "create_task", {"short_description": "x"}, raise_on_error=False
            )
            validate_error(
                tools, "create_task", result, "SESSION_REQUIRED", "not_attempted"
            )

    asyncio.run(run())
    upstream.session.request.assert_not_called()


@pytest.mark.parametrize(
    "failure,code",
    [
        (requests.ConnectTimeout(SECRET), "TIMEOUT"),
        (requests.exceptions.InvalidURL(SECRET), "UPSTREAM_ERROR"),
    ],
)
def test_known_pre_dispatch_failures_are_not_attempted(upstream, failure, code):
    upstream.session.request.side_effect = failure

    async def run():
        async with Client(create_server(lambda: upstream), mode="legacy") as connection:
            tools = {t.name: t for t in await connection.list_tools()}
            pending = (
                await connection.call_tool("create_task", {"short_description": "x"})
            ).structured_content
            result = await connection.call_tool(
                "confirm_pending_write",
                {"preview_id": pending["preview_id"], "confirmed": True},
                raise_on_error=False,
            )
            validate_error(
                tools, "confirm_pending_write", result, code, "not_attempted"
            )
            assert (
                "may already have committed"
                not in result.structured_content["retry_guidance"]
            )

    asyncio.run(run())
    upstream.session.request.assert_called_once()


def test_unknown_tool_is_a_protocol_error(upstream):
    from mcp.shared.exceptions import MCPError

    async def run():
        async with Client(create_server(lambda: upstream), mode="legacy") as connection:
            with pytest.raises(MCPError) as caught:
                await connection.call_tool(SECRET, {}, raise_on_error=False)
            assert caught.value.error.code == -32602
            assert SECRET not in str(caught.value)

    asyncio.run(run())
    upstream.session.request.assert_not_called()
