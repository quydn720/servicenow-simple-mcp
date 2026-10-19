"""Compare the incident state labels list_incidents accepts with the instance.

Run with an account that can read sys_choice (for example an admin on a
non-production clone): python -m servicenow_mcp.cli.check_incident_states
Exit codes: 0 match, 1 mismatch, 2 the choices could not be read.
"""

from __future__ import annotations

import sys

from servicenow_mcp.client import ServiceNowClient
from servicenow_mcp.config.environment import load_environment
from servicenow_mcp.config.local import Settings
from servicenow_mcp.errors import OperationError
from servicenow_mcp.tools.service_desk.search import INCIDENT_STATE_CODES

CHOICE_QUERY = "name=incident^element=state^language=en^inactive=false"


def instance_states(client: ServiceNowClient) -> dict[str, str]:
    """Return the instance's active incident state choices as label -> code."""
    rows = client.list_records(
        "sys_choice", query=CHOICE_QUERY, fields=["label", "value"], limit=100
    )
    return {row["label"]: row["value"] for row in rows if row.get("label")}


def compare(expected: dict[str, str], live: dict[str, str]) -> list[str]:
    """Return one line per problem; an empty list means the mapping matches."""
    problems = []
    for label, code in expected.items():
        if label not in live:
            problems.append(f"{label!r} (code {code}) is not an active state on the instance")
        elif live[label] != code:
            problems.append(f"{label!r} maps to {code} here but {live[label]} on the instance")
    for label in sorted(set(live) - set(expected)):
        problems.append(f"instance state {label!r} (code {live[label]}) cannot be searched")
    return problems


def main() -> int:
    load_environment()
    try:
        client = ServiceNowClient(Settings.from_env())
        live = instance_states(client)
    except (OperationError, RuntimeError) as error:
        print(f"Could not read incident state choices: {error}", file=sys.stderr)
        print("Use an account that can read the sys_choice table.", file=sys.stderr)
        return 2
    if not live:
        print("No incident state choices were visible to this account.", file=sys.stderr)
        return 2
    problems = compare(INCIDENT_STATE_CODES, live)
    for problem in problems:
        print("MISMATCH:", problem)
    if problems:
        print("Update INCIDENT_STATE_CODES in tools/service_desk/search.py to match.")
        return 1
    print(f"All {len(INCIDENT_STATE_CODES)} incident state labels match the instance.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
