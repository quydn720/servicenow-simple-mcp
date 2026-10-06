# Service-desk tool specifications

The local `service_desk` feature supplies these workflows. It does not add tools
to the remote server, which still exposes only the common read tools. Discovery
does not need credentials. Responsible ownership is the service-desk tool
maintainers; the deploying platform owner must record verified instance roles,
field limits, choices, and ACL prerequisites before release. These initial
specifications do not certify full project compliance or live-instance behavior.

Names use the existing approved `list` verb for bounded searches. New contracts
start at **1.0.0**, independent of package and MCP versions. Each new tool has
initial input/output snapshots linked below. Initial
changelog: introduce the specified bounded workflow. Compatible additions receive
a minor version; corrections receive a patch version; breaking changes require a
major version and a new tool name with `_v2`, retaining a migration period under
the [design standard](mcp-tool-design-standard.md#5-contract-versioning).
The existing `create_incident` contract is reused without changing its arguments
or successful result shapes; historical versioning for existing tools remains
pending.

## Shared contract and permissions

Every input rejects undeclared arguments. Raw record/reference IDs are 32 hex
characters. Limits are strict integers 1–100, default 10. Search text is trimmed,
nonblank, at most 160 characters; carets, control characters and case-insensitive
`javascript:` expressions (including whitespace before the colon) are rejected
before client creation. Only fixed field names/operators are generated internally;
no tool accepts caller-supplied encoded queries, scripts, or an approval override.
An invalid raw `query` argument on these new tools is an undeclared-input
`VALIDATION_ERROR`; the legacy common/Agile query arguments retain their explicit
`RAW_QUERY_PROHIBITED` behavior.

Authentication uses the configured local integration identity through Basic or
OAuth. Each read requires that identity's target-table and returned-field read
ACLs. Incident creation requires incident create/field ACLs; journal updates
require incident write ACLs and permission to the selected journal fields.
Confirmation obtains a client and current credentials before attempting the saved
operation; ServiceNow enforces current ACLs. Preview creation validates locally
and does not prove that the identity can perform the eventual write. Feature
selection and confirmation IDs do not grant authority. There is no universal role
assertion: actual roles, scopes, and record restrictions remain instance review
requirements. The existing lack of explicit per-tool authorization and complete
audit records remains a [compliance gap](mcp-tool-design-standard.md#current-compliance-gaps).

Read results use `{table, count, records}` for searches and
`{table, sys_id, record}` for retrieval. Returned sys_ids stay raw; references are
display names, other values are raw strings, and unavailable fields may be omitted.
Outputs discard undeclared upstream fields, require a valid sys_id, check retrieved
IDs against the requested ID, and validate types and bounds before returning.
Search count is the returned length, not the total; ordering is unspecified and
there is no pagination or truncation indicator. An empty search is successful.

All tools publish the standard structured error variant with MCP `isError: true`.
Applicable read/preparation errors:

| Code | Trigger and recovery |
| --- | --- |
| `VALIDATION_ERROR` | Missing/invalid arguments, prohibited literal syntax, unknown fields, or invalid cross-field combination; correct inputs before retrying |
| `AUTHENTICATION_REQUIRED` | Missing/invalid credentials or upstream 401; resolve authentication |
| `PERMISSION_DENIED` | Upstream 403; resolve identity/ACL requirements |
| `NOT_FOUND` | Missing/inaccessible record or endpoint; verify ID and access |
| `UPSTREAM_ERROR` | Upstream failure or malformed response; follow `retryable` |
| `TIMEOUT` | Upstream timeout; reads may retry only when `retryable=true` |
| `INTERNAL_ERROR` | Unexpected server failure; investigate, without exposing internal details |

Preparation additionally uses `SESSION_REQUIRED` for unsupported stateless
connections and `PREVIEW_LIMIT_EXCEEDED` for capacity exhaustion. Reads can fail
with `outcome=failed` or `not_attempted`; preparation failures are `not_attempted`.
Errors never expose upstream bodies or exception text. Confirmation additionally
uses `CONFIRMATION_INVALID` for expired, cancelled, replayed or cross-session IDs.
Write errors always have `retryable=false`; a dispatched write can have an unknown
outcome. See [error handling](error-handling.md) and [write review](write-review.md)
for exact error schemas, confirmation behavior, and reconciliation guidance.

## `list_incidents` — 1.0.0

Module: `tools/service_desk/incidents.py`. Read-only, fixed `incident` table.
Inputs: optional `search_text` and exact `number` (`INC` plus 1–20 digits), with
at least one non-null value required; optional `limit`. When both are present they
are combined with AND. Search text matches only `short_description` using LIKE.
No arbitrary filters, record writes, or approval are supported.

Returned fields: sys_id, number, short_description, description, state, priority,
assignment_group, assigned_to, caller_id, active, sys_created_on, sys_updated_on.
The same fieldset is used by incident details and confirmed incident writes.

Schemas: [input](tool-contracts/list_incidents/1.0.0/input.schema.json),
[output](tool-contracts/list_incidents/1.0.0/output.schema.json).

Example arguments: `{"search_text":"VPN","number":"INC0001","limit":10}`.
Example result: `{"table":"incident","count":1,"records":[{"sys_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","number":"INC0001","short_description":"VPN unavailable"}]}`.

## `get_incident` — 1.0.0

Module: `tools/service_desk/incidents.py`. Read-only, fixed `incident` table.
Required input `sys_id`; returns at most one record with the incident fieldset
above. No field-selection argument, attachments, journal/activity history, bulk
read, pagination, or write behavior. The existing `get_incident` prompt is retained
as a separate MCP prompt; this adds an actual tool.

Schemas: [input](tool-contracts/get_incident/1.0.0/input.schema.json),
[output](tool-contracts/get_incident/1.0.0/output.schema.json).

Example arguments: `{"sys_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}`.
Example result: `{"table":"incident","sys_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","record":{"sys_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","number":"INC0001","state":"2"}}`.

## `list_knowledge_articles` — 1.0.0

Module: `tools/service_desk/knowledge.py`. Read-only, fixed `kb_knowledge` table.
Required `search_text`; optional raw `knowledge_base` sys_id and `limit`.
Matches title (`short_description`) using LIKE, combined with fixed
`active=true` and `workflow_state=published` predicates. A supplied base adds an
exact `kb_knowledge_base` condition. This is summary search, not a full-text,
semantic, or Knowledge Management API search.

Returned fields: sys_id, number, short_description, kb_knowledge_base,
workflow_state, active, valid_to, sys_updated_on. Article bodies, attachments,
drafts, and writes are unsupported. This Table API implementation relies on the
execution identity's ACLs; it does not independently enforce portal user criteria
or exclude expired valid_to dates. Verify the intended knowledge audience on the
target instance. It must not be treated as a user-criteria-aware portal endpoint.

Schemas: [input](tool-contracts/list_knowledge_articles/1.0.0/input.schema.json),
[output](tool-contracts/list_knowledge_articles/1.0.0/output.schema.json).

Example arguments: `{"search_text":"VPN","limit":5}`.
Example result: `{"table":"kb_knowledge","count":1,"records":[{"sys_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","number":"KB0001","short_description":"VPN setup","workflow_state":"published","active":"true"}]}`.

## `create_incident` — existing contract

Module: `tools/service_desk/incidents.py`. Required `short_description`, trimmed,
nonblank, at most 160 characters. Only this field is writable; other incident
fields receive ServiceNow defaults. Returns one insertion preview and performs no
ServiceNow call until confirmation. Existing schemas are described in
[implemented contracts](tool-contracts.md); this request does not rename or
silently expand the existing tool.

Example arguments: `{"short_description":"VPN unavailable"}`. The result is
`{status:"awaiting_confirmation", preview_id, preview, expires_in_seconds:600, message}`
with preview `{operation:"insert", table:"incident", fields:{short_description:"VPN unavailable"}}`.

## `update_incident_journal` — 1.0.0

Module: `tools/service_desk/incidents.py`. Required target `sys_id`; optional
`work_notes` and `comments`, with at least one non-null value required. Each entry
is trimmed, nonblank, at most 4000 characters. Omission/null leaves a journal
unchanged; empty strings are rejected. No unrelated field updates, deletion,
history editing, attachments, or bulk writes.

Returns one update preview without contacting ServiceNow. Confirmation appends
entries rather than replacing prior journal entries. Work notes are internal;
comments may be customer-visible and trigger notifications under instance rules.
These journal semantics follow the [ServiceNow journal-field documentation](https://www.servicenow.com/docs/r/platform-administration/table-administration-and-data-management/r_JournalFields.html).

Schemas: [input](tool-contracts/update_incident_journal/1.0.0/input.schema.json),
[output](tool-contracts/update_incident_journal/1.0.0/output.schema.json).

Example arguments: `{"sys_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","work_notes":"Investigating VPN connectivity"}`.
The result is `{status:"awaiting_confirmation", preview_id, preview, expires_in_seconds:600, message}`
with preview `{operation:"update", table:"incident", sys_id:"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", fields:{work_notes:"Investigating VPN connectivity"}}`.

Show the complete preview, wait for approval in a subsequent user reply, then
call `confirm_pending_write` with the returned ID and `confirmed=true`;
`confirmed=false` cancels. Changes require a new preview and approval. IDs are
server/session-bound, expire after 600 seconds, and are consumed before one write
attempt. Restart loses previews; stateless writes are unsupported. Human approval
is conversational and cannot be independently verified by the server. Never
automatically retry writes. If outcome is unknown, reconcile the instance before
preparing and approving another preview: resubmission may duplicate a journal
entry. These same lifecycle rules apply to `create_incident`.

## `get_change_status` — 1.0.0

Module: `tools/service_desk/changes.py`. Read-only, fixed `change_request` table.
Required `sys_id`; returns at most one record. Supported fields: sys_id, number,
short_description, state, approval, type, sys_updated_on. State, approval, and type
are raw instance choice codes, not interpreted lifecycle labels. No approvals,
state transitions, updates, arbitrary filters, or pagination.

Schemas: [input](tool-contracts/get_change_status/1.0.0/input.schema.json),
[output](tool-contracts/get_change_status/1.0.0/output.schema.json).

Example arguments: `{"sys_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}`.
Example result: `{"table":"change_request","sys_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","record":{"sys_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","number":"CHG0001","state":"-1","approval":"requested"}}`.

## Review and verification

Mocked MCP-boundary tests cover service-desk-only discovery, schema conformance,
invalid inputs, query injection rejection, exact internal query construction,
field projection, malformed upstream results, journal preview/cancellation,
confirmation replay, authorization failures, and unknown write outcomes. Shared
write tests cover expiration and session isolation. No live ServiceNow calls are
used. Before release, the platform owner must verify instance permissions and
dictionary constraints, especially journal lengths and knowledge visibility.
