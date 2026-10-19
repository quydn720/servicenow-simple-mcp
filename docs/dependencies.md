# Dependencies

Runtime dependencies are pinned in `uv.lock`. CI (`.github/workflows/ci.yml`)
runs the tests on Python 3.11 and 3.13 and scans the locked runtime
dependencies with `pip-audit` on every pull request, on every push to `main`,
and weekly. Dependabot proposes dependency and GitHub Actions updates.

FastMCP is pinned exactly (`fastmcp==4.0.5` in `pyproject.toml`) because the
remote broker relies on its OAuth proxy internals. Upgrade it only in its own
pull request, after the full test suite passes and a live connector sign-in and
tool call succeed.

## Decision log

| Date | Dependency | Decision | Reason |
| --- | --- | --- | --- |
| 2026-10-19 | FastMCP 4.0.5 → 4.1.1 | Stay on 4.0.5; upgrade after 2026-11-01 | `pip-audit` finds no known vulnerabilities in the locked set. The 4.1.x security fixes cover features this server does not use (regex tool search, skills folders, MultiAuth, OpenAPI). 4.1.0 changes OAuth proxy behavior the broker uses, and 4.1.1 was released 2026-10-18. A trial upgrade passed all 345 tests; the upgrade still needs a live connector check. |
