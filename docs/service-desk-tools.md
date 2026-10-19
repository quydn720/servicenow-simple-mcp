# Service-desk tool specifications

The local `service_desk` feature supplies these workflows. Supported deployment
modes: local stdio provides every tool below. The remote OAuth server
(`servicenow_mcp.servers.remote`) also provides the read-only `list_incidents`,
`get_incident`, `get_incident_v3`, `list_knowledge_articles`, and
`get_change_status`, executed with the connected user's ServiceNow token. Write
preparation tools stay local-only, because previews are session-bound and the
remote server uses stateless HTTP. Discovery does not need credentials. Responsible ownership is the service-desk tool
maintainers; the deploying platform owner must record verified instance roles,
field limits, choices, and ACL prerequisites before release. These initial
specifications do not certify full project compliance or live-instance behavior.

Names use the existing approved `list` verb for bounded searches. New contracts
start at **1.0.0**, independent of package and MCP versions. Each new tool has
initial input/output snapshots linked below. Initial
changelog: introduce the specified bounded workflow. Compatible additions receive
a minor version; corrections receive a patch version; breaking changes require a
major version and a new tool name with the corresponding suffix (`_v2`, `_v3`, etc.), retaining a migration period under
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
requirements. Complete audit coverage across every tool remains a
[compliance gap](mcp-tool-design-standard.md#current-compliance-gaps); incident
search emits the safe audit event described below.

Read results use `{table, count, records}` for searches and `{table, record}` for
incident retrieval. ServiceNow display values are used for choice and reference
fields. Incident search and detail responses omit `sys_id`; incident details can
be retrieved by exact incident number or sys_id. Outputs discard undeclared
upstream fields, validate types and bounds, and check retrieved IDs when an ID was
requested. Search count is the returned length, not the total. Incident search is
ordered by most recently updated, then sys_id for stable pagination. A full page
can include `next_offset`; offsets are bounded to 100000. An empty search is
successful.

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

## `list_incidents` — 2.0.0

Module: `tools/service_desk/incidents.py`. Read-only, fixed `incident` table.
Inputs: at least one of `search_text`, exact `number` (`INC` plus 1–20 digits),
state display label, assignment-group sys_id, caller sys_id, `updated_after`, or
`updated_before` is required. Filters combine with AND. Search text is a literal
`short_description` substring. Date bounds are RFC 3339 UTC values applied to
`sys_updated_on`; the start is inclusive and the end exclusive. `limit` is 1–100
(default 10), and `offset` is 0–100000 (default 0). Results are ordered by update
time descending with sys_id as a hidden tie-breaker. A full page may include
`next_offset`; that field is omitted at the offset ceiling. Caller records and
fields remain subject to the configured ServiceNow identity's ACLs.

Returned fields: number, its `url` filtered by incident number, short_description,
state, priority, and sys_updated_on. The URL opens the ServiceNow incident list
filtered to that ticket; it contains no sys_id. Choice values use their ServiceNow
display labels. Search activity is audit logged with the MCP client identity when
available, filter names, outcome, and result count; values and record identifiers
are not logged.

Schemas: [input](tool-contracts/list_incidents/2.0.0/input.schema.json),
[output](tool-contracts/list_incidents/2.0.0/output.schema.json).

Example arguments: `{"search_text":"VPN","number":"INC0001","limit":1}`.
Example result: `{"table":"incident","count":1,"records":[{"number":"INC0001","url":"https://instance.service-now.com/incident_list.do?sysparm_query=number%3DINC0001","short_description":"VPN unavailable","state":"Open","priority":"Low - 4"}],"next_offset":1}`.

## `get_incident` — 2.0.0

Module: `tools/service_desk/incidents.py`. Read-only, fixed `incident` table.
Requires exactly one of `sys_id` or exact incident `number`. Returns one approved
incident record with a number-filtered `url`; neither the response nor URL exposes
sys_id. Attachments and journal/activity history are excluded. No field-selection
argument, bulk read, pagination, or write behavior.

Schemas: [input](tool-contracts/get_incident/2.0.0/input.schema.json),
[output](tool-contracts/get_incident/2.0.0/output.schema.json).

Example arguments: `{"number":"INC0001"}`.
Example result: `{"table":"incident","record":{"number":"INC0001","url":"https://instance.service-now.com/incident_list.do?sysparm_query=number%3DINC0001","state":"Open","priority":"Low - 4"}}`.

## `get_incident_v3` — 3.0.0

Module: `tools/service_desk/incidents.py`. Read-only, fixed `incident` table.
Requires exactly one non-null `sys_id` or exact incident `number`. Uses the
configured local ServiceNow identity and its ACLs; this tool does not delegate
analyst identity or allow a caller to request additional fields. The approved
detail fields remain number, short_description, description, state, priority,
assignment_group, assigned_to, caller_id, active, sys_created_on, and
sys_updated_on. The response adds a number-filtered `url`; sys_id is not returned.

The required `redaction` object always lists `journal_history`, `attachments`,
and `non_allowlisted_fields` in `excluded_categories`. These are policy
exclusions, not claims that such content existed. `omitted_fields` lists
allowlisted fields absent from the returned record; absence does not establish
that an ACL caused it. Work notes, comments, activity history, attachment
metadata/content, and non-allowlisted fields are not requested or returned.
This initial release does not expose those fields even when the configured
identity has access, and it does not scan approved free text for PII.

Number lookup is bounded to two results to detect ambiguity. No match returns
the standard safe `NOT_FOUND`; malformed or ambiguous results return
`UPSTREAM_ERROR`. Access-denied and missing-record messages do not disclose
whether an inaccessible record exists. A value-free audit event records tool,
version, operation, outcome, and safe error code; the ServiceNow identity is
reported as unavailable because the current client does not expose a verified
identity label. This tool is registered only in the local `service_desk`
feature; the existing `get_incident` tool and prompt remain available unchanged.

Schemas: [input](tool-contracts/get_incident_v3/3.0.0/input.schema.json),
[output](tool-contracts/get_incident_v3/3.0.0/output.schema.json).

Example arguments: `{"number":"INC0001"}`.
Example result: `{"table":"incident","record":{"number":"INC0001","url":"https://instance.service-now.com/incident_list.do?sysparm_query=number%3DINC0001","state":"Open"},"redaction":{"excluded_categories":["journal_history","attachments","non_allowlisted_fields"],"omitted_fields":["short_description","description","priority","assignment_group","assigned_to","caller_id","active","sys_created_on","sys_updated_on"]}}`.

Migration is opt-in: clients that need the new redaction metadata can call
`get_incident_v3`; existing `get_incident` contract 2.0.0 and its schema snapshots
are unchanged. This release does not deprecate or remove the existing tool.

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
