# Common record tool specifications

`list_records` and `get_record` read records from a fixed set of five task
tables. They are registered by the local `common` feature and by the remote
connector. Owner: Do Ngoc Quy. Both are released at contract **1.0.0**,
published as `_meta.fastmcp.version`.

## `list_records` — 1.0.0

Status: released; deployment modes: local stdio, remote connector.
Purpose: browse a bounded page of records from one allowed table.

| Input | Contract |
| --- | --- |
| `table` | Required. One of `incident`, `task`, `sc_task`, `problem`, `change_request`. |
| `fields` | Optional unique, nonempty list of declared fields; omitted or null uses all of them. `sys_id` is always returned. |
| `limit` | Integer 1–100, default 10. Booleans and strings are rejected. |
| `query` | Omit or pass null. Any string is rejected with `RAW_QUERY_PROHIBITED` before ServiceNow is contacted. |

Declared fields: sys_id, number, short_description, description, state,
priority, assignment_group, assigned_to, caller_id, active, sys_created_on,
sys_updated_on. References are display names; every other value is the raw
string, including choice codes and UTC timestamps. Fields the record lacks, or
the caller cannot read, are omitted.

Result: `{table, count, records}`. `count` is the number returned, not the
total. There is no pagination and no truncation indicator, and ordering is set
by ServiceNow, so a full page may have more matches.

Schemas: [input](tool-contracts/list_records/1.0.0/input.schema.json),
[output](tool-contracts/list_records/1.0.0/output.schema.json).

Example arguments: `{"table":"incident","fields":["number","short_description","state"],"limit":1}`.
Example result: `{"table":"incident","count":1,"records":[{"sys_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","number":"INC0010001","short_description":"Printer problem","state":"2"}]}`.

## `get_record` — 1.0.0

Status: released; deployment modes: local stdio, remote connector.
Purpose: read one record whose sys_id is known.

| Input | Contract |
| --- | --- |
| `table` | Required; the same five tables as `list_records`. |
| `sys_id` | Required; exactly 32 hexadecimal characters. |
| `fields` | As for `list_records`. |

Result: `{table, sys_id, record}`. The server checks that the returned record's
sys_id matches the requested one; a mismatch is `UPSTREAM_ERROR`.

Schemas: [input](tool-contracts/get_record/1.0.0/input.schema.json),
[output](tool-contracts/get_record/1.0.0/output.schema.json).

Example arguments: `{"table":"incident","sys_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","fields":["number","state"]}`.
Example result: `{"table":"incident","sys_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","record":{"sys_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","number":"INC0010001","state":"2"}}`.

## Permissions

- **Local stdio:** every call uses the configured integration account; its
  table, record and field ACLs decide what is returned.
- **Remote connector:** every call uses the signed-in user's own ServiceNow
  token, so their ACLs apply. The outbound client allows only GET requests to
  the five tables (and `kb_knowledge` for knowledge search).
- Neither tool writes, runs scripts, or accepts a caller-supplied query.

## Errors

Both tools return the standard error object with MCP `isError: true`
([error handling](error-handling.md)).

| Code | When | Retry |
| --- | --- | --- |
| `VALIDATION_ERROR` | Unknown table or field, bad sys_id, limit out of range, unknown argument | No; fix the input |
| `RAW_QUERY_PROHIBITED` | `query` is a string (`list_records`) | No; omit `query` |
| `AUTHENTICATION_REQUIRED` | No valid ServiceNow credentials or sign-in | No; sign in again |
| `PERMISSION_DENIED` | ServiceNow returned 403 | No |
| `NOT_FOUND` | The record does not exist or is not visible (`get_record`) | No |
| `TIMEOUT`, `UPSTREAM_ERROR` | ServiceNow timed out or failed | Only when `retryable` is true |

Example: `{"table":"incident","query":"active=true"}` returns
`{"status":"error","code":"RAW_QUERY_PROHIBITED","retryable":false,"outcome":"not_attempted",…}`.

## Version history

| Version | Changes |
| --- | --- |
| 1.0.0 (current) | Baseline contract: allowlisted tables and fields, limit 1–100, raw queries rejected. |
