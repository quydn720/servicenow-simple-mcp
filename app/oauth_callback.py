from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = 8765


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        request = urlparse(self.path)
        if request.path != "/callback":
            self.send_error(404)
            return

        params = parse_qs(request.query)
        code = params.get("code", [""])[0]
        error = params.get("error", [""])[0]

        self.send_response(200 if code else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if code:
            self.wfile.write(
                b"<h1>Authorization received</h1>"
                b"<p>You can return to the terminal and exchange the code.</p>"
            )
            print(f"Authorization code received: {code}")
            print("Keep this terminal open until you have exchanged the code.")
        else:
            self.wfile.write(f"<h1>Authorization failed</h1><p>{error}</p>".encode())
            print(f"Authorization failed: {error or 'unknown error'}")

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    server = HTTPServer((HOST, PORT), CallbackHandler)
    print(f"Listening for OAuth callback at http://localhost:{PORT}/callback")
    print("Press Ctrl+C after the authorization code appears.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nOAuth callback listener stopped.")
    finally:
        server.server_close()
