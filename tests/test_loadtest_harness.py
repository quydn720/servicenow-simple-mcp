"""The load-test harness keeps working: full sign-in, then error-free tool calls."""

import json
import subprocess
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1] / "loadtest" / "run.py"


def test_local_harness_signs_in_and_completes_calls_without_errors():
    # A separate process: the harness patches global HTTP functions to simulate ServiceNow.
    result = subprocess.run(
        [sys.executable, str(HARNESS), "--servicenow-ms", "0", "--levels", "1,4",
         "--requests", "8", "--json"],
        capture_output=True, text=True, timeout=120, check=True)
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["mode"] == "local"
    assert set(report["sign_in_ms"]) == {"register", "authorize", "consent", "callback", "token"}
    assert [level["errors"] for level in report["levels"]] == [0, 0]
    assert [level["requests"] for level in report["levels"]] == [8, 8]


def test_remote_mode_requires_a_token():
    result = subprocess.run([sys.executable, str(HARNESS), "--url", "https://mcp.example.com/mcp"],
                            capture_output=True, text=True, timeout=60,
                            env={"PATH": "", "MCP_LOADTEST_TOKEN": ""})
    assert result.returncode != 0
    assert "MCP_LOADTEST_TOKEN" in result.stderr
