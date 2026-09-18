from __future__ import annotations

import secrets
import threading
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import dotenv_values, set_key

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
HOST = "127.0.0.1"
PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/callback"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    result: dict[str, str] = {}
    expected_state = ""
    server: Optional[HTTPServer] = None

    def do_GET(self) -> None:
        request = urlparse(self.path)
        if request.path != "/callback":
            self.send_error(404)
            return

        params = parse_qs(request.query)
        state = params.get("state", [""])[0]
        code = params.get("code", [""])[0]
        error = params.get("error", [""])[0]

        if state != self.expected_state:
            type(self).result = {"error": "OAuth state validation failed"}
            status = 400
            body = "Authorization failed: invalid state."
        elif error:
            type(self).result = {"error": error}
            status = 400
            body = f"Authorization failed: {error}"
        elif not code:
            type(self).result = {"error": "No authorization code received"}
            status = 400
            body = "Authorization failed: no code received."
        else:
            type(self).result = {"code": code}
            status = 200
            body = "Authorization complete. You can close this browser tab."

        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<h1>{escape(body)}</h1>".encode())
        if self.server:
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, format: str, *args: object) -> None:
        return


def read_required_settings() -> tuple[str, str, str]:
    values = dotenv_values(ENV_FILE)
    instance = (values.get("SERVICENOW_INSTANCE") or "").strip().rstrip("/")
    client_id = (values.get("SERVICENOW_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (values.get("SERVICENOW_OAUTH_CLIENT_SECRET") or "").strip()

    missing = [
        name for name, value in (
            ("SERVICENOW_INSTANCE", instance),
            ("SERVICENOW_OAUTH_CLIENT_ID", client_id),
            ("SERVICENOW_OAUTH_CLIENT_SECRET", client_secret),
        ) if not value or value.startswith("your-")
    ]
    if missing:
        raise RuntimeError(f"Missing OAuth configuration in .env: {', '.join(missing)}")
    if not instance.startswith(("http://", "https://")):
        instance = f"https://{instance}"
    return instance, client_id, client_secret


def main() -> None:
    instance, client_id, client_secret = read_required_settings()
    state = secrets.token_urlsafe(24)
    authorization_url = f"{instance}/oauth_auth.do?{urlencode({
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': REDIRECT_URI,
        'state': state,
    })}"

    OAuthCallbackHandler.expected_state = state
    OAuthCallbackHandler.result = {}
    server = HTTPServer((HOST, PORT), OAuthCallbackHandler)
    OAuthCallbackHandler.server = server
    print("Opening ServiceNow authorization in your browser...")
    print(f"Callback listener: {REDIRECT_URI}")
    if not webbrowser.open(authorization_url):
        print(f"Open this URL manually:\n{authorization_url}")
    try:
        server.serve_forever()
    finally:
        server.server_close()

    result = OAuthCallbackHandler.result
    if "error" in result:
        raise RuntimeError(result["error"])

    response = requests.post(
        f"{instance}/oauth_token.do",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "code": result["code"],
        },
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"OAuth token exchange failed (HTTP {response.status_code})")

    token_data = response.json()
    refresh_token = token_data.get("refresh_token", "")
    if not refresh_token:
        raise RuntimeError("OAuth response did not include a refresh_token")

    set_key(str(ENV_FILE), "SERVICENOW_OAUTH_REFRESH_TOKEN", refresh_token)
    set_key(str(ENV_FILE), "SERVICENOW_OAUTH_ACCESS_TOKEN", "")
    print("OAuth setup complete. The refresh token was saved to .env (value hidden).")


if __name__ == "__main__":
    main()
