# Changelog

Notable changes to the ServiceNow MCP server. Each tool's contract version is
published as `_meta.fastmcp.version` and documented in
[docs/service-desk-tools.md](docs/service-desk-tools.md); this file records
server releases. Owner: Do Ngoc Quy.

## Release process

1. Add the release's changes under **Unreleased** in the pull request that makes them.
2. To release, rename **Unreleased** to `[X.Y.Z] - YYYY-MM-DD`, set the same
   version in `pyproject.toml`, and merge.
3. Tag the merge commit on `main` as `vX.Y.Z` and push the tag.
4. A breaking tool-contract change requires a major tool version and a
   **Breaking** entry with migration notes (design standard, section 5).

## [Unreleased]

## [0.1.0] - 2026-10-19

First tagged release. It covers all work merged to `main` up to PR #6.

### Added
- Local stdio MCP server with feature groups and Basic or OAuth
  authentication (initial commits).
- Display names for reference fields in returned records (PR #1).
- `src/` package layout, Agile story/epic/product tools, and the remote OAuth
  broker for per-user ServiceNow sign-in with read-only `list_records` and
  `get_record` (PR #2).
- Typed input/output contracts, structured errors, preview-then-confirm for
  every write (`confirm_pending_write`), and the service-desk tools
  `list_incidents`, `get_incident`, `create_incident`, `update_incident_journal`,
  `list_knowledge_articles`, `get_change_status` (PR #3).
- Service-desk read tools on the remote connector; incident search filters
  (state, assignment group, caller, update dates), stable ordering, pagination,
  and number-filtered ServiceNow links (PR #5).
- Tool contract versions published in tool metadata (PR #6).

### Breaking
- `list_incidents` is now contract 2.0.0 and `get_incident` is 3.0.0: no
  `sys_id` in results, `state`/`priority` as display labels, lookup by
  incident number, and a `redaction` object on `get_incident`. See
  [migrating from 1.0.0](docs/service-desk-tools.md#migrating-from-100) (PR #6).
- Raw `query` arguments on list tools are rejected with `RAW_QUERY_PROHIBITED` (PR #3).

[Unreleased]: https://github.com/quydn720/servicenow-simple-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/quydn720/servicenow-simple-mcp/releases/tag/v0.1.0
