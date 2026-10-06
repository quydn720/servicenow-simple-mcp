# Implemented MCP tool contracts

The authoritative definitions are in `src/servicenow_mcp/tools/contracts.py`.
All 15 tools publish JSON Schema 2020-12 inputs and explicit outputs in discovery.
Registration through `contract_tool` validates direct and MCP calls and validates
structured results. Discovery needs no credentials or ServiceNow requests.
These contracts also apply to the remote `get_record` and `list_records` tools.

## Inputs and validation

| Input | Implemented contract |
| --- | --- |
| `table` | incident, task, sc_task, problem, or change_request for common tools; fixed table for each Agile tool |
| `sys_id` and create references | Exactly 32 hexadecimal characters; either case accepted, no whitespace or display names |
| Update product/epic references | A sys_id, or empty string to clear; omission/null leaves unchanged |
| `short_description` | String, trimmed before validation, nonblank, maximum 160 characters |
| Description/acceptance criteria | String, trimmed, maximum 4000 characters; optional null/omission leaves unspecified; empty string is retained explicitly |
| `priority` | String choice `1`–`5`; create defaults to `3`; update null/omission leaves unchanged |
| `story_points` | Integer 0–100; boolean and string coercions rejected; optional null/omission leaves unspecified |
| `limit` | Integer 1–100, default 10; booleans/strings rejected; no pagination |
| `fields` | Nonempty unique list of declared fields; omission/null uses defaults; `sys_id` is always included |
| `query` | Omission/null only; every string is blocked with `RAW_QUERY_PROHIBITED` |
| `preview_id` | Nonempty string up to 128 characters; must identify a live preview in this server/session |
| `confirmed` | Strict boolean; no replacement fields accepted |

Unknown input arguments are rejected. Invalid individual arguments fail before
client creation. Updates with no changed fields fail before saving a preview.
Create null optional values are omitted from payloads; explicit empty text is
saved as empty text. Description/HTML lengths and priority choices are project
bounds, not a claim about every instance: verify dictionary lengths, choices,
and ACLs in each target instance before deployment. This change makes no live
instance calls and does not change ServiceNow ACLs.

## Declared record fields

| Tools / tables | Allowed/default fields |
| --- | --- |
| Common get/list; incident/task write results | sys_id, number, short_description, description, state, priority, assignment_group, assigned_to, caller_id, active, sys_created_on, sys_updated_on |
| Story get/list/write; rm_story | sys_id, number, short_description, description, acceptance_criteria, story_points, priority, product, epic |
| Epic get/list/write; rm_epic | sys_id, number, short_description, description, product, priority |
| Product get/list; cmdb_model | sys_id, name |

Read requests send explicit fieldsets to ServiceNow. Returned records are
projected to the selected fields plus sys_id. Write results are projected to the
table's declared fields. Extra fields are discarded rather than disclosed.
Every returned record must have a valid sys_id; get results must match the
requested ID. Other record fields may be omitted, but explicit nulls or incorrect
types are rejected. Table API values are strings, including raw priority,
story_points, active, and timestamps. Reference fields are display names.

## Output variants

| Operation | Structured result |
| --- | --- |
| Get | `{table, sys_id, record}` with typed record fields |
| List | `{table, count, records}`; count equals returned length, length cannot exceed requested limit |
| Create/update preparation | `{status: "awaiting_confirmation", preview_id, preview, expires_in_seconds: 600, message}` or existing write error |
| Confirmation success | `{table, record}` with table-specific record fields |
| Cancellation | `{status: "cancelled", preview, message}` |
| Existing write error | `{status: "error", message}` with optional typed preview and retry_guidance |

Previews define the exact operation/table, allowed payload fields, and an ID for
updates. Structured output objects forbid undeclared properties. Malformed read
results fail as tool errors. Malformed saved-write results return the existing
write failure with reconciliation guidance; preview IDs remain consumed so that
the write is not replayed. The 600-second session-bound preview lifecycle and
explicit approval policy are unchanged.

## Compatibility and remaining work

Tool names and successful JSON envelope shapes are retained. Clients must adjust
if they used malformed IDs, invalid priority codes, oversized text, arbitrary
fields, duplicate/empty fieldsets, out-of-range limits, or coercible non-string/
non-integer arguments. Common reads now default to the declared narrow fieldset;
clients relying on undeclared output fields must stop doing so. `sys_id` is
always returned even when not explicitly selected. FastMCP Python clients may
parse typed results into models; use `structured_content` for the JSON object.

This completes the typed-contract/validation implementation, not full standards
compliance. Stable error codes/envelopes, consistent `isError` signaling for
legacy write errors, per-tool permission review, contract versions/snapshots,
and deprecation/migration governance remain separate work. The original standard's
read/write examples are illustrative target contracts, not substitutes for these
runtime definitions. Raw-query exceptions and structured filters remain disabled.
