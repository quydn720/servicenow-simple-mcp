from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from flask import Flask, jsonify, render_template

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_MODULE = "app.server"

app = Flask(__name__)
_process: Optional[subprocess.Popen[Any]] = None
_process_started_at: Optional[str] = None
_process_lock = threading.Lock()
_events: list[dict[str, str]] = []


def _record_event(message: str) -> None:
    _events.insert(0, {
        "message": message,
        "time": datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S"),
    })
    del _events[10:]


def _is_running() -> bool:
    return _process is not None and _process.poll() is None


def _status() -> dict[str, Any]:
    running = _is_running()
    return {
        "running": running,
        "pid": _process.pid if running and _process else None,
        "started_at": _process_started_at if running else None,
        "events": _events,
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    return jsonify(_status())


@app.post("/api/server/start")
def start_server():
    global _process, _process_started_at

    with _process_lock:
        if _is_running():
            return jsonify(_status())

        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        _process = subprocess.Popen(
            [sys.executable, "-m", SERVER_MODULE],
            cwd=PROJECT_ROOT,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _process_started_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        _record_event("MCP server started")
        return jsonify(_status()), 201


@app.post("/api/server/stop")
def stop_server():
    global _process, _process_started_at

    with _process_lock:
        if not _is_running():
            _process = None
            _process_started_at = None
            return jsonify(_status())

        assert _process is not None
        if _process.stdin:
            _process.stdin.close()
        _process.terminate()
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()
            _process.wait(timeout=5)

        _record_event("MCP server stopped")
        _process = None
        _process_started_at = None
        return jsonify(_status())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
