import asyncio
import os
from unittest.mock import Mock

import pytest
import requests

from app.server import create_server


def tools(server):
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for key in list(os.environ):
        if key.startswith('SERVICENOW_') or key == 'MCP_ENABLED_FEATURES':
            monkeypatch.delenv(key)
    monkeypatch.setattr(requests.sessions.Session, 'request', Mock(side_effect=AssertionError('Network during discovery')))


def test_default_discovery():
    server = create_server()
    assert set(tools(server)) == {'list_records', 'get_record', 'create_task', 'create_incident', 'create_agile_story'}
    assert {p.name for p in asyncio.run(server.list_prompts())} == {'get_incident'}


@pytest.mark.parametrize('features, expected', [
    (' common, common ', {'list_records', 'get_record'}),
    ('service_desk', {'create_task', 'create_incident'}),
    ('product_owner', {'create_agile_story'}),
    ('developer', set()),
])
def test_feature_selection(monkeypatch, features, expected):
    monkeypatch.setenv('MCP_ENABLED_FEATURES', features)
    server = create_server()
    assert set(tools(server)) == expected
    assert bool(asyncio.run(server.list_prompts())) == ('service_desk' in features)


@pytest.mark.parametrize('features', ['', ' , ', 'unknown', 'common,unknown'])
def test_invalid_features(monkeypatch, features):
    monkeypatch.setenv('MCP_ENABLED_FEATURES', features)
    with pytest.raises(RuntimeError, match='MCP_ENABLED_FEATURES'):
        create_server()


def test_migrated_payloads_and_results():
    client = Mock()
    client.create_record.return_value = {'sys_id': 'created'}
    client.list_records.return_value = [{'sys_id': 'existing'}]
    client.get_record.return_value = {'sys_id': 'existing'}
    factory = Mock(return_value=client)
    registered = tools(create_server(factory))
    result = registered['create_task'].fn(' Task ', description=' Details ', assignment_group=' group ')
    client.create_record.assert_called_with('task', {'short_description': 'Task', 'description': 'Details', 'priority': '3', 'assignment_group': 'group'})
    assert result == {'table': 'task', 'record': {'sys_id': 'created'}}
    assert registered['create_incident'].fn(' Incident ') == {'table': 'incident', 'record': {'sys_id': 'created'}}
    client.create_record.assert_called_with('incident', {'short_description': 'Incident'})
    assert registered['create_agile_story'].fn(' Story ', ' Description ', ' Criteria ', 0, '2') == {'table': 'rm_story', 'record': {'sys_id': 'created'}}
    client.create_record.assert_called_with('rm_story', {'short_description': 'Story', 'description': 'Description', 'acceptance_criteria': 'Criteria', 'story_points': 0, 'priority': '2'})
    assert registered['list_records'].fn('incident', 'active=true', ['sys_id'], 2) == {'table': 'incident', 'count': 1, 'records': [{'sys_id': 'existing'}]}
    client.list_records.assert_called_with(table='incident', query='active=true', fields=['sys_id'], limit=2)
    assert registered['get_record'].fn('incident', 'existing', ['sys_id']) == {'table': 'incident', 'sys_id': 'existing', 'record': {'sys_id': 'existing'}}
    client.get_record.assert_called_with(table='incident', sys_id='existing', fields=['sys_id'])
    assert factory.call_count == 5


@pytest.mark.parametrize('name, args', [
    ('create_task', [' ']), ('create_incident', ['']), ('create_agile_story', ['']),
    ('create_agile_story', ['Story', None, None, 101]),
    ('create_agile_story', ['Story', None, None, -1]),
    ('list_records', ['sys_user']), ('get_record', ['sys_user', 'id']),
    ('list_records', ['']), ('get_record', ['incident', '']),
])
def test_validation_before_client_creation(name, args):
    factory = Mock(side_effect=AssertionError('Client created before validation'))
    registered = tools(create_server(factory))
    with pytest.raises(ValueError):
        registered[name].fn(*args)
    factory.assert_not_called()
