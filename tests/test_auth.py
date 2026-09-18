from dataclasses import replace
from unittest.mock import Mock

import pytest
import requests

from app.config import Settings
from app.service_now_client import ServiceNowClient


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, 'request', Mock(side_effect=AssertionError('Unexpected network')))


def test_basic_does_not_exchange_tokens(monkeypatch):
    post = Mock(side_effect=AssertionError('OAuth called'))
    monkeypatch.setattr(requests, 'post', post)
    client = ServiceNowClient(Settings('example.test', auth_type='basic', username='user', password='pass'))
    prepared = client.session.prepare_request(requests.Request('GET', 'https://example.test'))
    assert prepared.headers['Authorization'] == 'Basic dXNlcjpwYXNz'
    post.assert_not_called()


def test_access_token_only(monkeypatch):
    monkeypatch.setattr(requests, 'post', Mock(side_effect=AssertionError('OAuth called')))
    client = ServiceNowClient(Settings('example.test', oauth_access_token='token'))
    assert client.session.headers['Authorization'] == 'Bearer token'


def test_refresh_preferred(monkeypatch):
    post = Mock(return_value=Mock(status_code=200, json=lambda: {'access_token': 'fresh'}))
    monkeypatch.setattr(requests, 'post', post)
    settings = Settings('example.test/', 'id', 'secret', 'refresh', 'stale')
    client = ServiceNowClient(settings)
    assert client.session.headers['Authorization'] == 'Bearer fresh'
    assert post.call_args.args == ('https://example.test/oauth_token.do',)
    assert post.call_args.kwargs['data'] == {'grant_type': 'refresh_token', 'client_id': 'id', 'client_secret': 'secret', 'refresh_token': 'refresh'}


@pytest.mark.parametrize('response', [
    Mock(status_code=401, text='secret response'),
    Mock(status_code=200, json=Mock(side_effect=ValueError('secret response'))),
    Mock(status_code=200, json=lambda: {}),
    Mock(status_code=200, json=lambda: []),
])
def test_oauth_failures_sanitized(monkeypatch, response):
    monkeypatch.setattr(requests, 'post', Mock(return_value=response))
    with pytest.raises(RuntimeError) as error:
        ServiceNowClient(Settings('example.test', 'id', 'secret', 'refresh'))
    assert 'secret' not in str(error.value)


def test_network_failure_sanitized(monkeypatch):
    monkeypatch.setattr(requests, 'post', Mock(side_effect=requests.ConnectionError('secret')))
    with pytest.raises(RuntimeError, match='check connectivity') as error:
        ServiceNowClient(Settings('example.test', 'id', 'secret', 'refresh'))
    assert error.value.__suppress_context__


@pytest.mark.parametrize('changes, message', [
    ({'auth_type': 'other'}, 'SERVICENOW_AUTH_TYPE'),
    ({'instance': ''}, 'SERVICENOW_INSTANCE'),
    ({'username': ''}, 'SERVICENOW_USERNAME'),
    ({'password': ''}, 'SERVICENOW_PASSWORD'),
    ({'auth_type': 'oauth'}, 'REFRESH_TOKEN'),
    ({'auth_type': 'oauth', 'oauth_refresh_token': 'token'}, 'CLIENT_ID'),
    ({'auth_type': 'oauth', 'oauth_refresh_token': 'token', 'oauth_client_id': 'id'}, 'CLIENT_SECRET'),
])
def test_settings_validation(changes, message):
    settings = replace(Settings('example.test', auth_type='basic', username='user', password='pass'), **changes)
    with pytest.raises(RuntimeError, match=message):
        settings.validate()


def test_environment_selection(monkeypatch):
    for key in list(__import__('os').environ):
        if key.startswith('SERVICENOW_'):
            monkeypatch.delenv(key)
    monkeypatch.setenv('SERVICENOW_INSTANCE', 'example.test')
    monkeypatch.setenv('SERVICENOW_OAUTH_ACCESS_TOKEN', 'token')
    assert Settings.from_env().auth_type == 'oauth'
    monkeypatch.setenv('SERVICENOW_AUTH_TYPE', 'basic')
    monkeypatch.setenv('SERVICENOW_USERNAME', 'user')
    monkeypatch.setenv('SERVICENOW_PASSWORD', ' pass ')
    assert Settings.from_env().password == ' pass '


def test_api_failure_hides_body():
    client = ServiceNowClient(Settings('example.test', oauth_access_token='token'))
    client.session.request = Mock(return_value=Mock(status_code=401, text='secret'))
    with pytest.raises(RuntimeError, match='HTTP 401') as error:
        client.list_records('incident')
    assert 'secret' not in str(error.value)
    assert client.session.request.call_count == 1
