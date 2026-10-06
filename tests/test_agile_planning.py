from unittest.mock import Mock

import pytest
import requests

from servicenow_mcp.servers.stdio import create_server
from conftest import reviewed_tools

ID = "0123456789abcdef0123456789abcdef"
EPIC = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


@pytest.fixture
def agile(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED_FEATURES", "product_owner")
    monkeypatch.setattr(requests.sessions.Session, "request", Mock(side_effect=AssertionError("Unexpected network")))
    client = Mock()
    client.create_record.return_value = {"sys_id": ID}
    client.update_record.return_value = {"sys_id": ID}
    client.get_record.return_value = {"sys_id": ID}
    client.list_records.return_value = [{"sys_id": ID}]
    factory = Mock(return_value=client)
    server = create_server(factory)
    registered = reviewed_tools(server)
    factory.assert_not_called()
    return registered, client, factory


def test_create_story_references_and_html(agile):
    tools, client, _ = agile
    result = tools["create_agile_story"].fn(
        " Story ", " Details ", " <p>Given <b>x</b></p> ", 100, "2", ID, EPIC,
    )
    client.create_record.assert_called_once_with("rm_story", {
        "short_description": "Story", "description": "Details",
        "acceptance_criteria": "<p>Given <b>x</b></p>", "story_points": 100,
        "priority": "2", "product": ID, "epic": EPIC,
    })
    assert result == {"table": "rm_story", "record": {"sys_id": ID}}
    assert tools["create_agile_story"].parameters["required"] == ["short_description"]


@pytest.mark.parametrize("entity,table", [("story", "rm_story"), ("epic", "rm_epic")])
def test_minimal_create(agile, entity, table):
    tools, client, _ = agile
    assert tools[f"create_agile_{entity}"].fn(" Title ") == {"table": table, "record": {"sys_id": ID}}
    client.create_record.assert_called_once_with(table, {"short_description": "Title", "priority": "3"})


def test_epic_create_all_fields(agile):
    tools, client, _ = agile
    tools["create_agile_epic"].fn(" Epic ", " Details ", ID.upper(), "1")
    client.create_record.assert_called_once_with("rm_epic", {
        "short_description": "Epic", "description": "Details", "product": ID.upper(), "priority": "1",
    })


@pytest.mark.parametrize("entity,table", [("story", "rm_story"), ("epic", "rm_epic")])
def test_update_partial_and_clear(agile, entity, table):
    tools, client, _ = agile
    result = tools[f"update_agile_{entity}"].fn(ID, description="", product="", priority=None)
    client.update_record.assert_called_once_with(table, ID, {"description": "", "product": ""})
    assert result == {"table": table, "record": {"sys_id": ID}}


def test_story_update_all_fields(agile):
    tools, client, _ = agile
    tools["update_agile_story"].fn(ID, " Title ", " Details ", "<p>Criteria</p>", 0, "2", ID, EPIC)
    client.update_record.assert_called_once_with("rm_story", ID, {
        "short_description": "Title", "description": "Details", "acceptance_criteria": "<p>Criteria</p>",
        "story_points": 0, "priority": "2", "product": ID, "epic": EPIC,
    })


def test_story_clear_epic_and_criteria(agile):
    tools, client, _ = agile
    tools["update_agile_story"].fn(ID, epic="", acceptance_criteria="")
    client.update_record.assert_called_once_with("rm_story", ID, {"epic": "", "acceptance_criteria": ""})


@pytest.mark.parametrize("name,kwargs", [
    ("create_agile_story", {"short_description": " "}),
    ("create_agile_epic", {"short_description": ""}),
    ("create_agile_story", {"short_description": "Story", "product": "name"}),
    ("create_agile_story", {"short_description": "Story", "epic": "x" * 32}),
    ("create_agile_epic", {"short_description": "Epic", "product": ""}),
    ("update_agile_story", {"sys_id": ID}),
    ("update_agile_epic", {"sys_id": ID, "description": None}),
    ("update_agile_story", {"sys_id": ID, "short_description": " "}),
    ("update_agile_epic", {"sys_id": ID, "short_description": ""}),
    ("update_agile_story", {"sys_id": ID, "story_points": -1}),
    ("update_agile_story", {"sys_id": ID, "story_points": 101}),
    ("update_agile_epic", {"sys_id": ID, "product": "invalid"}),
    ("update_agile_story", {"sys_id": "", "description": "Details"}),
    ("get_agile_product", {"sys_id": "name"}),
])
def test_invalid_inputs_before_client_creation(agile, name, kwargs):
    tools, _, factory = agile
    # Cross-field update validation still uses the existing write-error shape.
    if name.startswith("update_") and kwargs in ({"sys_id": ID}, {"sys_id": ID, "description": None}):
        assert tools[name].fn(**kwargs)["status"] == "error"
    else:
        with pytest.raises(ValueError):
            tools[name].fn(**kwargs)
    factory.assert_not_called()


@pytest.mark.parametrize("entity,plural,table,display", [
    ("story", "stories", "rm_story", "short_description"),
    ("epic", "epics", "rm_epic", "short_description"),
    ("product", "products", "cmdb_model", "name"),
])
def test_reads(agile, entity, plural, table, display):
    tools, client, _ = agile
    result = tools[f"get_agile_{entity}"].fn(ID)
    assert result == {"table": table, "sys_id": ID, "record": {"sys_id": ID}}
    kwargs = client.get_record.call_args.kwargs
    assert kwargs["table"] == table and kwargs["sys_id"] == ID
    assert {"sys_id", display} <= set(kwargs["fields"])
    tools[f"get_agile_{entity}"].fn(ID, ["sys_id"])
    client.get_record.assert_called_with(table=table, sys_id=ID, fields=["sys_id"])
    result = tools[f"list_agile_{plural}"].fn()
    assert result == {"table": table, "count": 1, "records": [{"sys_id": ID}]}
    kwargs = client.list_records.call_args.kwargs
    assert kwargs["table"] == table and kwargs["limit"] == 10 and kwargs["query"] is None
    assert {"sys_id", display} <= set(kwargs["fields"])
    tools[f"list_agile_{plural}"].fn(None, ["sys_id"], 100)
    client.list_records.assert_called_with(table=table, query=None, fields=["sys_id"], limit=100)
    client.list_records.return_value = []
    assert tools[f"list_agile_{plural}"].fn()["count"] == 0


@pytest.mark.parametrize("name,method,kwargs", [
    ("create_agile_story", "create_record", {"short_description": "Story"}),
    ("create_agile_epic", "create_record", {"short_description": "Epic"}),
    ("update_agile_story", "update_record", {"sys_id": ID, "description": "Update"}),
    ("update_agile_epic", "update_record", {"sys_id": ID, "description": "Update"}),
    ("get_agile_product", "get_record", {"sys_id": ID}),
    ("list_agile_stories", "list_records", {}),
])
def test_errors_propagate_without_retry(agile, name, method, kwargs):
    tools, client, _ = agile
    error = RuntimeError("ServiceNow request failed (HTTP 403)")
    getattr(client, method).side_effect = error
    if name.startswith(("create_", "update_")):
        result = tools[name].fn(**kwargs)
        assert result["status"] == "error" and result["message"] == str(error)
    else:
        with pytest.raises(RuntimeError) as caught:
            tools[name].fn(**kwargs)
        assert caught.value is error
    assert getattr(client, method).call_count == 1
