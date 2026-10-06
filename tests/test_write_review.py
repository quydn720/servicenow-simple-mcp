import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastmcp import Client

from servicenow_mcp.config.local import Settings
from servicenow_mcp.servers.stdio import create_server
from servicenow_mcp.client import ServiceNowClient
from servicenow_mcp.errors import OperationError
from servicenow_mcp.tools import write_review

ID = '0123456789abcdef0123456789abcdef'
WRITES = [
    ('create_incident', {'short_description': ' Incident '}, 'incident', None),
    ('create_task', {'short_description': ' Task '}, 'task', None),
    ('create_agile_story', {'short_description': ' Story '}, 'rm_story', None),
    ('create_agile_epic', {'short_description': ' Epic '}, 'rm_epic', None),
    ('update_agile_story', {'sys_id': ID, 'description': ''}, 'rm_story', ID),
    ('update_agile_epic', {'sys_id': ID, 'product': ''}, 'rm_epic', ID),
]


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv('MCP_ENABLED_FEATURES', 'common,service_desk,product_owner')
    client = Mock()
    client.create_record.return_value = {'sys_id': ID}
    client.update_record.return_value = {'sys_id': ID}
    factory = Mock(return_value=client)
    mcp = create_server(factory)
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    ctx = SimpleNamespace(fastmcp=mcp, session_id='test-session')
    return mcp, tools, client, factory, ctx


def invoke(tool, ctx, **kwargs):
    return asyncio.run(tool.fn(ctx=ctx, **kwargs))


@pytest.mark.parametrize('name,arguments,table,sys_id', WRITES)
@pytest.mark.parametrize('approved', [True, False])
def test_preview_and_confirmation_for_every_write(server, name, arguments, table, sys_id, approved):
    _, tools, client, factory, ctx = server
    result = invoke(tools[name], ctx, **arguments)
    factory.assert_not_called()
    assert result['status'] == 'awaiting_confirmation'
    assert result['expires_in_seconds'] == 600
    preview = result['preview']
    assert preview['table'] == table
    assert preview['operation'] == ('update' if sys_id else 'insert')
    if sys_id:
        assert preview['sys_id'] == sys_id
    else:
        assert preview['fields']['short_description'] == arguments['short_description'].strip()
    result = invoke(tools['confirm_pending_write'], ctx,
                    preview_id=result['preview_id'], confirmed=approved)
    if approved:
        if sys_id:
            client.update_record.assert_called_once_with(table, sys_id, preview['fields'])
        else:
            client.create_record.assert_called_once_with(table, preview['fields'])
        assert result == {'table': table, 'record': {'sys_id': ID}}
    else:
        factory.assert_not_called()
        assert result['status'] == 'cancelled'


def test_desktop_compatible_without_elicitation(server):
    mcp, _, client, factory, _ = server
    async def run():
        # No elicitation handler: this reproduces Desktop's missing capability.
        async with Client(mcp, mode='legacy') as connection:
            result = await connection.call_tool('create_agile_story', {'short_description': ' Story '})
            pending = result.data
            assert pending['status'] == 'awaiting_confirmation'
            factory.assert_not_called()
            assert pending['preview']['fields'] == {'short_description': 'Story', 'priority': '3'}
            result = await connection.call_tool('confirm_pending_write', {
                'preview_id': pending['preview_id'], 'confirmed': True,
            })
            assert result.data == {'table': 'rm_story', 'record': {'sys_id': ID}}
    asyncio.run(run())
    client.create_record.assert_called_once_with('rm_story', {'short_description': 'Story', 'priority': '3'})


def test_stateless_connection_returns_actionable_error(server):
    mcp, _, _, factory, _ = server
    async def run():
        async with Client(mcp, mode='2026-07-28') as connection:
            result = await connection.call_tool('create_incident', {'short_description': 'Incident'}, raise_on_error=False)
            assert result.structured_content['status'] == 'error'
            assert "mode='legacy'" in result.structured_content['message']
    asyncio.run(run())
    factory.assert_not_called()


@pytest.mark.parametrize('approved', [True, False])
def test_preview_is_single_use(server, approved):
    _, tools, client, factory, ctx = server
    pending = invoke(tools['create_incident'], ctx, short_description='Incident')
    kwargs = {'preview_id': pending['preview_id'], 'confirmed': approved}
    invoke(tools['confirm_pending_write'], ctx, **kwargs)
    again = invoke(tools['confirm_pending_write'], ctx, **kwargs)
    assert again['code'] == 'CONFIRMATION_INVALID' and 'already used' in again['message']
    assert factory.call_count == int(approved)
    assert client.create_record.call_count == int(approved)


def test_expired_and_unknown_preview_do_not_write(server, monkeypatch):
    _, tools, _, factory, ctx = server
    monkeypatch.setattr(write_review, 'monotonic', lambda: 100)
    pending = invoke(tools['create_incident'], ctx, short_description='Incident')
    monkeypatch.setattr(write_review, 'monotonic', lambda: 701)
    for token in [pending['preview_id'], 'unknown']:
        result = invoke(tools['confirm_pending_write'], ctx, preview_id=token, confirmed=True)
        assert result['status'] == 'error'
    factory.assert_not_called()


def test_other_sessions_and_servers_cannot_confirm(server):
    mcp, tools, _, factory, ctx = server
    pending = invoke(tools['create_incident'], ctx, short_description='Incident')
    foreign_ctx = SimpleNamespace(fastmcp=mcp, session_id='other-session')
    result = invoke(tools['confirm_pending_write'], foreign_ctx,
                    preview_id=pending['preview_id'], confirmed=True)
    assert result['status'] == 'error'
    other = create_server(factory)
    other_tools = {t.name: t for t in asyncio.run(other.list_tools())}
    other_ctx = SimpleNamespace(fastmcp=other, session_id=ctx.session_id)
    assert invoke(other_tools['confirm_pending_write'], other_ctx,
                  preview_id=pending['preview_id'], confirmed=True)['status'] == 'error'
    factory.assert_not_called()
    # Attempts in other sessions do not consume the owner's preview.
    assert invoke(tools['confirm_pending_write'], ctx,
                  preview_id=pending['preview_id'], confirmed=True)['record']['sys_id'] == ID


def test_preview_cannot_be_modified_after_review(server):
    _, tools, client, _, ctx = server
    pending = invoke(tools['create_incident'], ctx, short_description='Original')
    pending['preview']['fields']['short_description'] = 'Modified'
    pending['preview']['table'] = 'sys_user'
    invoke(tools['confirm_pending_write'], ctx, preview_id=pending['preview_id'], confirmed=True)
    client.create_record.assert_called_once_with('incident', {'short_description': 'Original'})
    parameters = tools['confirm_pending_write'].parameters
    assert set(parameters['properties']) == {'preview_id', 'confirmed'}
    assert parameters['required'] == ['preview_id', 'confirmed']


def test_validation_and_authentication_errors(server):
    _, tools, _, factory, ctx = server
    invalid = invoke(tools['create_incident'], ctx, short_description=' ')
    assert invalid['code'] == 'VALIDATION_ERROR'
    factory.assert_not_called()
    pending = invoke(tools['create_incident'], ctx, short_description='Incident')
    factory.side_effect = OperationError('AUTHENTICATION_REQUIRED')
    result = invoke(tools['confirm_pending_write'], ctx, preview_id=pending['preview_id'], confirmed=True)
    assert result['status'] == 'error'
    assert result['code'] == 'AUTHENTICATION_REQUIRED'
    assert result['outcome'] == 'not_attempted'


def test_concurrent_confirmation_inserts_only_once(server):
    _, tools, client, _, ctx = server
    pending = invoke(tools['create_incident'], ctx, short_description='Incident')
    def confirm(_):
        return invoke(tools['confirm_pending_write'], ctx,
                      preview_id=pending['preview_id'], confirmed=True)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(confirm, range(2)))
    assert sum('record' in result for result in results) == 1
    assert sum(result.get('status') == 'error' for result in results) == 1
    client.create_record.assert_called_once()


def test_pending_preview_capacity(server, monkeypatch):
    _, tools, _, factory, ctx = server
    monkeypatch.setattr(write_review, 'MAX_PENDING_PREVIEWS', 1)
    pending = invoke(tools['create_incident'], ctx, short_description='First')
    assert invoke(tools['create_incident'], ctx, short_description='Second')['status'] == 'error'
    invoke(tools['confirm_pending_write'], ctx, preview_id=pending['preview_id'], confirmed=False)
    assert invoke(tools['create_incident'], ctx, short_description='Third')['status'] == 'awaiting_confirmation'
    factory.assert_not_called()


@pytest.mark.parametrize('body,status,code,outcome', [
    ({'error': {'message': 'secret', 'detail': 'secret'}}, 403, 'PERMISSION_DENIED', 'failed'),
    ({'error': {'message': 'secret'}}, 200, 'UPSTREAM_ERROR', 'unknown'),
    ({'result': {}}, 200, 'UPSTREAM_ERROR', 'unknown'),
    ([], 200, 'UPSTREAM_ERROR', 'unknown'),
])
def test_servicenow_error_messages(body, status, code, outcome):
    client = ServiceNowClient(Settings('example.test', oauth_access_token='token'))
    client.session.request = Mock(return_value=Mock(status_code=status, json=Mock(return_value=body)))
    with pytest.raises(OperationError) as caught:
        client.create_record('incident', {'short_description': 'Incident'})
    assert caught.value.code == code
    assert caught.value.outcome == outcome
    assert 'secret' not in str(caught.value)
    client.session.request.assert_called_once()


def test_write_timeout_is_not_retried(server):
    _, tools, client, _, ctx = server
    client.create_record.side_effect = OperationError('TIMEOUT', outcome='unknown')
    pending = invoke(tools['create_incident'], ctx, short_description='Incident')
    kwargs = {'preview_id': pending['preview_id'], 'confirmed': True}
    result = invoke(tools['confirm_pending_write'], ctx, **kwargs)
    assert result['code'] == 'TIMEOUT' and result['outcome'] == 'unknown'
    assert result['retryable'] is False
    assert 'may already have committed' in result['retry_guidance']
    assert invoke(tools['confirm_pending_write'], ctx, **kwargs)['status'] == 'error'
    client.create_record.assert_called_once()
