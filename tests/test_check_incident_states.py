from unittest.mock import Mock

import pytest

from servicenow_mcp.cli import check_incident_states as check
from servicenow_mcp.errors import OperationError

BASE = {"New": "1", "In Progress": "2", "On Hold": "3", "Resolved": "6", "Closed": "7", "Canceled": "8"}


def rows(mapping):
    return [{"label": label, "value": code} for label, code in mapping.items()]


def test_instance_states_reads_active_english_incident_choices():
    client = Mock()
    client.list_records.return_value = rows(BASE)
    assert check.instance_states(client) == BASE
    client.list_records.assert_called_once_with(
        "sys_choice", query=check.CHOICE_QUERY, fields=["label", "value"], limit=100
    )


def test_matching_mapping_has_no_problems():
    assert check.compare(BASE, dict(BASE)) == []


def test_changed_missing_and_unmapped_states_are_reported():
    live = {**BASE, "In Progress": "12", "Awaiting Vendor": "20"}
    del live["Canceled"]
    problems = check.compare(BASE, live)
    assert len(problems) == 3
    assert any("'In Progress' maps to 2 here but 12" in p for p in problems)
    assert any("'Canceled'" in p and "not an active state" in p for p in problems)
    assert any("'Awaiting Vendor'" in p and "cannot be searched" in p for p in problems)


@pytest.mark.parametrize("live,code", [(BASE, 0), ({**BASE, "New": "9"}, 1), ({}, 2)])
def test_main_exit_codes(monkeypatch, capsys, live, code):
    monkeypatch.setattr(check, "load_environment", lambda: None)
    monkeypatch.setattr(check.Settings, "from_env", classmethod(lambda cls: Mock()))
    monkeypatch.setattr(check, "ServiceNowClient", lambda settings: Mock())
    monkeypatch.setattr(check, "instance_states", lambda client: live)
    assert check.main() == code


def test_main_reports_access_errors_without_details(monkeypatch, capsys):
    monkeypatch.setattr(check, "load_environment", lambda: None)
    monkeypatch.setattr(check.Settings, "from_env", classmethod(lambda cls: Mock()))
    monkeypatch.setattr(check, "ServiceNowClient", lambda settings: Mock())

    def denied(client):
        raise OperationError("PERMISSION_DENIED", http_status=403)

    monkeypatch.setattr(check, "instance_states", denied)
    assert check.main() == 2
    assert "sys_choice" in capsys.readouterr().err
