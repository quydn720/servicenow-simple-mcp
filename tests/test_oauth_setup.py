from io import BytesIO

import pytest

from app.oauth_setup import OAuthCallbackHandler


@pytest.mark.parametrize('query, expected, status', [
    ('state=expected&code=test-code', {'code': 'test-code'}, 200),
    ('state=wrong&code=test-code', {'error': 'OAuth state validation failed'}, 400),
    ('state=expected&error=access_denied', {'error': 'access_denied'}, 400),
    ('state=expected', {'error': 'No authorization code received'}, 400),
])
def test_callback_shares_result_with_setup(query, expected, status):
    OAuthCallbackHandler.expected_state = 'expected'
    OAuthCallbackHandler.result = {}
    handler = object.__new__(OAuthCallbackHandler)
    handler.path = '/callback?' + query
    handler.server = None
    handler.wfile = BytesIO()
    statuses = []
    handler.send_response = statuses.append
    handler.send_header = lambda *args: None
    handler.end_headers = lambda: None

    handler.do_GET()

    assert OAuthCallbackHandler.result == expected
    assert statuses == [status]
