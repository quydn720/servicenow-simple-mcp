"""Validate the remote deployment's ServiceNow API access in an environment.

Run where the remote server is configured (development, test, production):

    servicenow-mcp-check-remote              # or: python -m servicenow_mcp.cli.check_remote
    servicenow-mcp-check-remote --json
    servicenow-mcp-check-remote --offline    # settings only, no network

It reads only and needs no user sign-in. It checks the environment policy and
secret sources, that ServiceNow recognizes the broker's OAuth client, that the
identity API refuses anonymous calls, and, if the server is reachable, its
discovery metadata and sign-in requirement. Exit code 0 means no failures.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass

import requests

from servicenow_mcp.config.environment import load_environment
from servicenow_mcp.config.remote import ENFORCED_ENVIRONMENTS, RemoteSettings

MANUAL = (
    ("first sign-in", "Sign in through the connector: proves the client secret and the redirect URL."),
    ("auth scope", "With POC_SERVICENOW_SCOPE set, a signed-in user's token is refused by an API outside the scope."),
    ("user access", "Two non-admin users see only their own permitted records (docs/remote-auth-poc.md)."),
)


@dataclass
class Check:
    area: str
    name: str
    result: str  # PASS, WARN or FAIL
    detail: str


def settings_checks(settings: RemoteSettings) -> list[Check]:
    enforced = settings.environment in ENFORCED_ENVIRONMENTS
    checks = [Check("settings", "environment", "PASS", settings.environment),
              Check("settings", "HTTPS", "PASS", f"{settings.public_url} -> {settings.instance}")]
    for name, source in sorted(settings.secret_sources.items()):
        if source == "dotenv":
            checks.append(Check("settings", name, "FAIL" if enforced else "WARN",
                                "plain text in .env.remote; use a secret file or the platform's secret store"))
        else:
            checks.append(Check("settings", name, "PASS", "secret file" if source == "file" else "injected by the platform"))
    for problem in settings.policy_violations():
        if "plain text" not in problem:
            checks.append(Check("settings", "environment policy", "FAIL" if enforced else "WARN", problem))
    return checks


def servicenow_checks(settings: RemoteSettings, http=requests) -> list[Check]:
    checks = []
    params = {"response_type": "code", "client_id": settings.client_id,
              "redirect_uri": settings.public_url + "/auth/callback", "state": "access-check"}
    if settings.servicenow_scope:
        params["scope"] = settings.servicenow_scope
    try:
        response = http.get(settings.instance + "/oauth_auth.do", params=params,
                            allow_redirects=False, timeout=20)
        if "unauthorized_client" in response.text.lower():
            checks.append(Check("servicenow", "OAuth client", "FAIL",
                                "ServiceNow does not recognize the client (inactive, or created on another instance)"))
        elif response.status_code in (200, 302):
            checks.append(Check("servicenow", "OAuth client", "PASS", "accepted; ServiceNow shows its sign-in"))
        else:
            checks.append(Check("servicenow", "OAuth client", "WARN", f"unexpected HTTP {response.status_code}"))
    except requests.RequestException:
        checks.append(Check("servicenow", "OAuth client", "FAIL", "instance not reachable"))
    try:
        status = http.get(settings.instance + settings.identity_path, timeout=20).status_code
        if status in (401, 403):
            checks.append(Check("servicenow", "identity API", "PASS", "refuses anonymous calls"))
        elif status == 200:
            checks.append(Check("servicenow", "identity API", "FAIL", "answers without authentication"))
        else:
            checks.append(Check("servicenow", "identity API", "WARN", f"unexpected HTTP {status}"))
    except requests.RequestException:
        checks.append(Check("servicenow", "identity API", "FAIL", "instance not reachable"))
    return checks


def broker_checks(settings: RemoteSettings, http=requests) -> list[Check]:
    try:
        metadata = http.get(settings.public_url + "/.well-known/oauth-authorization-server", timeout=10).json()
        unauthenticated = http.post(settings.public_url + "/mcp", json={}, timeout=10).status_code
    except (requests.RequestException, ValueError):
        return [Check("broker", "reachable", "WARN", "server not reachable at POC_PUBLIC_URL; re-run once deployed")]
    checks = []
    if "registration_endpoint" in metadata:
        checks.append(Check("broker", "registration", "FAIL" if settings.environment in ENFORCED_ENVIRONMENTS else "WARN",
                            "open /register is advertised"))
    else:
        checks.append(Check("broker", "registration", "PASS", "open /register is off"))
    checks.append(Check("broker", "revocation", "PASS" if metadata.get("revocation_endpoint") else "FAIL",
                        metadata.get("revocation_endpoint") or "no revocation endpoint advertised"))
    checks.append(Check("broker", "sign-in required", "PASS" if unauthenticated == 401 else "FAIL",
                        f"unauthenticated /mcp returned HTTP {unauthenticated}"))
    return checks


def run(offline: bool = False) -> tuple[list[Check], int]:
    load_environment(remote=True)
    try:
        settings = RemoteSettings.from_env()
    except ValueError as error:
        return [Check("settings", "configuration", "FAIL", str(error))], 1
    checks = settings_checks(settings)
    if not offline:
        checks += servicenow_checks(settings) + broker_checks(settings)
    checks += [Check("manual", name, "WARN", text) for name, text in MANUAL]
    return checks, int(any(c.result == "FAIL" for c in checks))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="servicenow-mcp-check-remote", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--offline", action="store_true", help="check settings only")
    args = parser.parse_args(argv)
    checks, code = run(args.offline)
    if args.json:
        print(json.dumps({"passed": code == 0, "checks": [asdict(c) for c in checks]}, indent=2))
        return code
    for check in checks:
        print(f"{check.result:<4}  {check.area:<10} {check.name:<30} {check.detail}")
    failures = sum(c.result == "FAIL" for c in checks)
    print(f"\n{failures} failure(s)." if failures else "\nNo failures.")
    return code


if __name__ == "__main__":
    sys.exit(main())
