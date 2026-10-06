from unittest.mock import Mock

import pytest

from servicenow_mcp.config.local import Settings
from servicenow_mcp.client import ServiceNowClient


ID = "a" * 32
GROUP_ID = "b" * 32


@pytest.fixture
def client():
    client = ServiceNowClient(Settings("example.test", oauth_access_token="token"))
    client.session.request = Mock()
    return client


def api_record():
    return {
        "sys_id": {"display_value": ID, "value": ID},
        "number": {"display_value": "INC0010001", "value": "INC0010001"},
        "assignment_group": {
            "display_value": "Service Desk", "value": GROUP_ID,
            "link": f"https://example.test/api/now/table/sys_user_group/{GROUP_ID}",
        },
        "assigned_to": {"display_value": "", "value": ""},
        "caller_id": {"display_value": "", "value": "c" * 32, "link": ""},
        "priority": {"display_value": "3 - Moderate", "value": "3"},
        "sys_created_on": {
            "display_value": "2026-10-06 14:00:00", "value": "2026-10-06 07:00:00",
        },
        "active": {"display_value": "true", "value": "true"},
        "short_description": "Printer problem",
    }


EXPECTED = {
    "sys_id": ID, "number": "INC0010001", "assignment_group": "Service Desk",
    "assigned_to": "", "caller_id": "", "priority": "3",
    "sys_created_on": "2026-10-06 07:00:00", "active": "true",
    "short_description": "Printer problem",
}


@pytest.mark.parametrize("operation,method", [
    ("list", "GET"), ("get", "GET"), ("create", "POST"), ("update", "PATCH"),
])
def test_reference_names_across_table_operations(client, operation, method):
    record = api_record()
    body = {"result": [record] if operation == "list" else record}
    client.session.request.return_value = Mock(status_code=200, json=Mock(return_value=body))
    fields = ["sys_id", "assignment_group", "priority"]
    payload = {"short_description": "Printer problem", "assignment_group": GROUP_ID}

    if operation == "list":
        result = client.list_records("incident", query=f"assignment_group={GROUP_ID}", fields=fields, limit=5)
        assert result == [EXPECTED]
    elif operation == "get":
        assert client.get_record("incident", ID, fields=fields) == EXPECTED
    elif operation == "create":
        assert client.create_record("incident", payload) == EXPECTED
    else:
        assert client.update_record("incident", ID, payload) == EXPECTED

    client.session.request.assert_called_once()
    request = client.session.request.call_args.kwargs
    assert request["method"] == method
    assert request["url"] == "https://example.test/api/now/table/incident" + (
        f"/{ID}" if operation in ("get", "update") else ""
    )
    params = request["params"]
    assert params["sysparm_display_value"] == "all"
    assert params["sysparm_exclude_reference_link"] == "false"
    if operation in ("list", "get"):
        assert params["sysparm_fields"] == ",".join(fields)
        assert request["json"] is None
    else:
        assert request["json"] == payload
        assert payload["assignment_group"] == GROUP_ID
    if operation == "list":
        assert params["sysparm_query"] == f"assignment_group={GROUP_ID}"
        assert params["sysparm_limit"] == 5


@pytest.mark.parametrize("body,expected", [
    ({"result": []}, []), ({}, []),
    ({"result": [{"sys_id": ID, "assignment_group": "Service Desk"}]},
     [{"sys_id": ID, "assignment_group": "Service Desk"}]),
])
def test_empty_and_plain_list_responses(client, body, expected):
    client.session.request.return_value = Mock(status_code=200, json=Mock(return_value=body))
    assert client.list_records("incident") == expected


@pytest.mark.parametrize("operation", ["create", "update"])
def test_empty_wrapped_id_is_not_a_successful_write(client, operation):
    body = {"result": {"sys_id": {"display_value": "", "value": ""}}}
    client.session.request.return_value = Mock(status_code=200, json=Mock(return_value=body))
    with pytest.raises(RuntimeError, match="ServiceNow could not complete"):
        if operation == "create":
            client.create_record("incident", {"short_description": "Printer problem"})
        else:
            client.update_record("incident", ID, {"short_description": "Printer problem"})
    client.session.request.assert_called_once()
