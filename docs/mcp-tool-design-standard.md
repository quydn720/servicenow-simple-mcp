# MCP tool design standard

Standard version: **1.0.0**. Published: **2026-10-06**.

This standard defines the target contract for ServiceNow MCP tools in this
repository. It is intended for tool authors and reviewers. **MUST** and
**MUST NOT** are mandatory project requirements; **SHOULD** permits a documented
reason for deviation. Approval of this document does not certify existing tools.
See [current compliance gaps](#current-compliance-gaps) before relying on enforcement.

## 1. Naming and required contract

Tool names MUST use lowercase snake_case: `<verb>_<resource>` or
`<verb>_<domain>_<resource>`. Names MUST be unique across all enabled feature
groups and MUST describe one bounded operation. Use singular resources for
single-record operations and plural resources for collections.

| Verb | Meaning | Example |
| --- | --- | --- |
| `get` | Retrieve one identified resource | `get_record` |
| `list` | Retrieve a bounded collection | `list_agile_stories` |
| `create` | Prepare creation of one resource | `create_task` |
| `update` | Prepare changes to one resource | `update_agile_story` |
| `delete` | Prepare deletion; requires a separately reviewed use case | `delete_task` |
| `confirm` | Execute or cancel an already prepared operation | `confirm_pending_write` |

These are the approved verbs. A new verb requires a reviewed update to this
standard. Names such as `run`, `execute`, and `do_action` MUST NOT hide a generic
executor. A naming example does not authorize implementation of that capability.
Domain qualifiers follow the verb, as in `get_agile_story`; do not introduce a
service prefix. A breaking major version appends `_v2`, `_v3`, and so on.

Every tool MUST have a reviewed specification containing:

- Name, responsible owner, contract version, and supported deployment modes.
- Published description, explicit input schema, and explicit output schema.
- Validation and normalization rules, including cross-field checks.
- Authentication, execution identity, permissions, and allowed resources.
- Side effects, limitations, confirmation requirements, and retry behavior.
- Defined error codes, recovery guidance, and valid input/output examples.
- Versioned schema snapshots, changelog, and any approved exceptions.

## 2. Descriptions, schemas, and validation

The published description MUST state what the tool does and when to use it,
supported tables and fields, result limits or pagination, unsupported operations,
and whether it reads, prepares a write, or commits a write. Write descriptions
MUST state approval requirements, preview lifetime, and retry restrictions.
Descriptions MUST NOT imply that preview creation has already saved a record.

Project tools MUST publish both `inputSchema` and `outputSchema`, even where
the protocol makes metadata optional. Use explicit JSON Schema 2020-12
`$schema` declarations, object inputs, field descriptions, required fields,
types, enums, size bounds, patterns, and defaults where applicable. Specify
whether optional values can be null. Reject unknown input properties using
`additionalProperties: false`, including inside filter and write objects.

Outputs MUST enumerate success, pending confirmation, cancellation, and error
variants applicable to that tool. Define each returned record field and its
representation; do not use an unconstrained `dict` as the contract. An optional
output field MUST NOT appear with an undocumented type. Project structured
error results MUST also be covered by the output schema.

The server MUST validate inputs before contacting ServiceNow and validate
structured results before returning them. Schema defaults are documentation;
the implementation MUST apply them explicitly. Specify whether validation runs
before or after normalization and reject invalid values without silently
discarding them. Allowlist tables, fields, filter operators, and writable fields.
Never forward an unvalidated caller object or arbitrary field name to the client.
Verify field lengths and choices against the target instance before release.

For collection tools, document a default and maximum result count, ordering,
pagination support, and how truncation is communicated. Raw reference identifiers
MUST be used for query/write inputs; returned reference display values MUST be
identified as display values. Preserve raw record `sys_id` values.

The [official MCP tools specification (2026-07-28)](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/server/tools.mdx)
defines `inputSchema`, `outputSchema`, and `structuredContent`. Structured output
must conform to its declared schema; serialized JSON text is recommended for
older clients. Tool execution failures use `isError: true`; malformed protocol
requests and unknown tools use JSON-RPC errors. Annotations are hints, not access
controls. The mandatory schemas, error envelope, naming, and approval policies
in this document are project requirements.

Transport envelopes MUST follow the negotiated MCP version. The JSON examples
below show arguments or `structuredContent`, not complete JSON-RPC messages.
This reference does not migrate the current session-based write workflow to a
different transport or protocol version.

## 3. Permissions and ServiceNow query policy

Every specification MUST identify authentication mode, execution identity
(integration account or delegated end user), verified role/scope prerequisites,
table/record/field ACL requirements, and operation allowlists. Instance-specific
roles MUST be verified and recorded before release; do not invent a universal
ServiceNow role requirement. Credentials MUST NOT be tool arguments or outputs.

The server MUST enforce authorization at invocation and at write confirmation.
ServiceNow ACLs remain authoritative; tool discovery and `MCP_ENABLED_FEATURES`
are not grants of permission. A preview ID MUST NOT bypass authorization.
Logs MUST record tool name/version, identity, operation, outcome, and applicable
exception ID without exposing tokens or sensitive record/query contents.

### Raw queries: deny by default

Caller-supplied ServiceNow encoded queries, direct `sysparm_query` passthrough,
and executable query or script expressions MUST NOT be executed without a
recorded exception. This includes expressions supplied through structured
filter values or other indirect arguments. Renaming `query` to `filter` does
not make passthrough compliant.

Ordinary tools MAY expose typed structured filters with allowlisted fields and
operators. The server MUST validate values and encode them safely when constructing
internal ServiceNow queries. Query delimiters and executable expressions MUST
NOT gain syntax meaning through string concatenation. A `sys_id` lookup or
server-built query from validated inputs is not a raw-query exception.

Only the designated security or platform owner may approve an exception.
The exception record MUST include:

| Required field | Content |
| --- | --- |
| Exception ID and approver | Traceable record and designated approving owner |
| Justification | Why structured filters do not meet the use case |
| Tools and versions | Exact capability covered |
| Environment and identities | Permitted instance/environment and callers |
| Tables and fields | Explicit access scope |
| Constraints | Allowed query forms, result bounds, execution limits, and audit requirements |
| Effective date and expiration | Bounded validity period |
| Revocation conditions | Conditions and owner responsible for revocation |

The server MUST check the trusted exception record before each raw-query
execution and reject missing, expired, revoked, or out-of-scope exceptions with
`RAW_QUERY_PROHIBITED`. A caller-supplied `approved=true`, ordinary user request,
or assistant judgment MUST NOT grant an exception. Query approval does not grant
write permission or override ACLs. Executable scripts require explicit inclusion
in the exception; approval of encoded queries alone does not authorize scripts.

## 4. Write lifecycle and errors

All write tools MUST follow [required review before ServiceNow writes](write-review.md).
New write tools MUST use `@return_write_errors` and `preview_write(...)` rather
than directly calling insert or update client methods. Any future deletion use
case must extend the reviewed workflow before implementation; current tools
only support insert and update.

1. Validate and normalize inputs. Return the complete saved payload in a preview
   without contacting ServiceNow. The current preview lifetime is 600 seconds.
2. Show the entire preview and wait for explicit approval in a subsequent user
   reply. The initial request, tool access, or another approval is insufficient.
3. Call `confirm_pending_write` with the saved ID and a strict boolean.
   `confirmed=false` cancels with no write; `confirmed=true` commits only the saved
   values. Changes require a fresh preview and fresh approval.
4. Bind previews to the originating server/session, expire them, and consume
   them once before any write attempt, including failed attempts. Restarting the
   server discards previews. Reject reused and cross-session IDs.
5. Return the saved record after success. ServiceNow defaults and business rules
   may alter it; preview values are not a guarantee of final persisted values.
6. Never automatically retry a write. If connectivity fails after dispatch,
   report that the outcome may be unknown and verify the instance before
   preparing another preview. Consuming an ID prevents replay of that ID, not
   duplication caused by submitting the same business request again.

Current confirmation is conversational: the server cannot independently prove
that an assistant's `confirmed=true` came from a human reply. The specification
and descriptions MUST disclose this limitation. Current previews require the
supported session-based connection; stateless connections are rejected. Any
future server-verified approval or stateless design requires separate work.

### Defined errors

Every tool MUST list its applicable codes, triggers, and recovery. Use a
structured envelope with `status: "error"`, `code`, safe `message`, `retryable`,
and `outcome` (`not_attempted`, `failed`, or `unknown`). `retryable` indicates
whether repeating an unchanged call is safe and potentially useful; it MUST be
false for write confirmation failures. Return the error with MCP `isError: true`.
Pending previews and cancellations are successful tool outcomes, not errors.

| Code | Trigger | Recovery |
| --- | --- | --- |
| `VALIDATION_ERROR` | Invalid type, bounds, choices, fields, or cross-field values | Correct arguments; no unchanged retry |
| `AUTHENTICATION_REQUIRED` | Missing, expired, or invalid credentials | Restore authentication |
| `PERMISSION_DENIED` | Operation/field denied by server policy or ServiceNow ACLs | Obtain verified access; do not bypass controls |
| `NOT_FOUND` | Authorized lookup has no matching record | Check identifier; avoid disclosing inaccessible records |
| `RAW_QUERY_PROHIBITED` | Raw-query use has no valid scoped exception | Use structured filters or obtain owner exception |
| `CONFIRMATION_INVALID` | Preview missing, expired, consumed, or from another session | Prepare and review a new preview; use one generic message |
| `SESSION_REQUIRED` | Unsupported stateless preview connection | Reconnect in the supported session mode |
| `PREVIEW_LIMIT_EXCEEDED` | Pending preview capacity reached | Cancel previews or wait for expiration |
| `UPSTREAM_ERROR` | ServiceNow rejects or cannot complete the request | Explain safe recovery; no automatic write retry |
| `TIMEOUT` | Deadline exceeded without a definitive response | Reads may retry; dispatched writes require reconciliation |
| `INTERNAL_ERROR` | Unexpected server failure | Return a safe message; investigate privately |

Map definitive upstream 401/403 responses to authentication/permission codes.
Do not expose access-protected record existence through `NOT_FOUND`. Mark
`not_attempted` when no ServiceNow operation was dispatched, `failed` only when
failure is definitive, and `unknown` when a dispatched write may have committed.
Do not map every connection failure to a known failed write.

Messages and logs MUST NOT expose credentials, headers, stack traces, raw response
bodies, or unrestricted sensitive data. Sanitized upstream HTTP status and
relevant structured details MAY be included when safe. The current error wrapper
does not yet supply the full envelope above; updating it is a compliance task.

## 5. Contract versioning

Each tool MUST have its own semantic contract version, initially `1.0.0`,
independent of package version, standard version, and negotiated MCP version.
The version belongs in the specification and release catalog; MCP does not
define a standard per-tool `version` field. Do not add an invented protocol field.

Store immutable, self-contained input/output schema snapshots for each released
contract version with the specification and changelog (for example,
`docs/tool-contracts/get_record/1.0.0/`). JSON Schema references MUST resolve
within the snapshot; copy shared definitions into `$defs` for publication.
Schemas generated from Python types still require review and snapshots.

| Change | Required version treatment |
| --- | --- |
| Clarification with unchanged observable behavior | Patch |
| Optional capability compatible with existing arguments, results, and strict consumers | Minor |
| Removed/renamed fields, new required inputs, incompatible types/enums/defaults, changed write semantics, or tighter accepted-input constraints | Major |

Adding output fields can break strict consumers; it is not automatically minor.
Changing error meanings or permission prerequisites requires compatibility review.
For a major change, expose a new name such as `get_record_v2` and preserve the
old contract during the documented migration window. State replacement, migration
steps, deprecation date, removal date, and affected clients. Security fixes may
require accelerated removal with owner approval and explicit release notice.
Never silently rewrite an old schema snapshot. This document neither renames
tools nor creates their release snapshots.

## 6. Reusable tool specification template

Copy this template for each tool; replace every placeholder before release.

```markdown
# <tool_name> — contract <major.minor.patch>

Owner: <accountable team/person>
Status: <proposed/released/deprecated>; deployment modes: <supported modes>
Purpose: <one bounded use case>
Published description: <purpose, limits, tables/fields, side effects, approval, retries>

## Schemas
Input schema: <self-contained JSON Schema and immutable snapshot link>
Output schema: <self-contained JSON Schema covering every applicable result variant>
Defaults/nullability: <what omission and null mean; how defaults are applied>

## Validation and limitations
<normalization order, field/table allowlists, lengths/choices, cross-field checks>
<result bounds, pagination, reference representation, unsupported operations>

## Permissions
<authentication modes, execution identity, verified roles/scopes, table/record/field ACLs>
<server checks and when they run; safe audit fields>
Raw-query policy: <none, or trusted exception ID/scope/expiration>

## Effects and recovery
<read-only, preview, or commit; confirmation lifetime/binding/single use>
<cancellation, retries, timeout/unknown-outcome recovery>
Errors: <applicable stable codes, triggers, safe messages, retryable/outcome rules>

## Examples and review
<valid arguments and every structured result variant, with MCP isError values>
<invalid/unauthorized/query/confirmation/replay/timeout scenarios>
Schemas/changelog: <versioned links>
Deprecation/migration: <none, or dates and replacement>
Reviewer and approval record: <verified instance prerequisites and exceptions>
```

## 7. Illustrative target-standard specifications

**These examples define a proposed target contract, not the current wire
contract.** They require implementation and compatibility review before release.
Use the versioning policy when migrating existing tools. Owners below are
responsible teams for illustration, not assertions of assigned ownership.

### `get_record` — illustrative contract 1.0.0

Owner: common-tools maintainers. Deployment: local stdio and authenticated remote
only after each mode's identity/ACL mapping is verified. Raw-query exceptions: none.

Published description:

> Read one incident, task, sc_task, problem, or change_request by its raw sys_id.
> Return only sys_id, number, and short_description; this contract does not
> accept custom fieldsets, queries, or pagination. No record is changed and no
> confirmation is needed. Reads may be retried after transient failures.

Validation: require exact table enum and 32 lowercase hexadecimal ID; do not
normalize identifiers silently. Fetch only the declared fieldset. One record
maximum. Missing optional fields are omitted, not returned as null. Permissions:
local Basic/OAuth integration identity or remote delegated OAuth identity needs
read access to the selected table, record, and returned fields. The release
specification MUST record verified instance roles/scopes and ACL checks.

Applicable errors: `VALIDATION_ERROR`, `AUTHENTICATION_REQUIRED`,
`PERMISSION_DENIED`, `NOT_FOUND`, `RAW_QUERY_PROHIBITED`, `UPSTREAM_ERROR`,
`TIMEOUT`, `INTERNAL_ERROR`. An unknown argument is a validation error;
`RAW_QUERY_PROHIBITED` applies if raw syntax reaches a policy guard. Read failures
have `outcome: "not_attempted"` before dispatch or `"failed"` after dispatch;
only transient read upstream/timeouts may set `retryable: true`.

Input schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "table": {"type": "string", "enum": ["incident", "task", "sc_task", "problem", "change_request"], "description": "Allowlisted table to read."},
    "sys_id": {"type": "string", "pattern": "^[0-9a-f]{32}$", "description": "Raw record identifier, not a display value."}
  },
  "required": ["table", "sys_id"]
}
```

Output schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "oneOf": [
    {
      "type": "object", "additionalProperties": false,
      "properties": {
        "table": {"type": "string", "enum": ["incident", "task", "sc_task", "problem", "change_request"], "description": "Requested table."},
        "sys_id": {"type": "string", "pattern": "^[0-9a-f]{32}$", "description": "Requested raw identifier."},
        "record": {
          "type": "object", "additionalProperties": false,
          "properties": {
            "sys_id": {"type": "string", "pattern": "^[0-9a-f]{32}$", "description": "Raw identifier; must match the requested ID."},
            "number": {"type": "string", "description": "Record number when available."},
            "short_description": {"type": "string", "description": "Record summary when available."}
          },
          "required": ["sys_id"]
        }
      },
      "required": ["table", "sys_id", "record"]
    },
    {
      "type": "object", "additionalProperties": false,
      "properties": {
        "status": {"const": "error", "description": "Execution failure."},
        "code": {"type": "string", "enum": ["VALIDATION_ERROR", "AUTHENTICATION_REQUIRED", "PERMISSION_DENIED", "NOT_FOUND", "RAW_QUERY_PROHIBITED", "UPSTREAM_ERROR", "TIMEOUT", "INTERNAL_ERROR"], "description": "Stable error code."},
        "message": {"type": "string", "minLength": 1, "description": "Safe recovery message."},
        "retryable": {"type": "boolean", "description": "Whether an unchanged read may safely be repeated."},
        "outcome": {"enum": ["not_attempted", "failed"], "description": "Whether the read was dispatched."}
      },
      "required": ["status", "code", "message", "retryable", "outcome"]
    }
  ]
}
```

Valid arguments:

```json
{"table": "incident", "sys_id": "0123456789abcdef0123456789abcdef"}
```

Success (`isError: false`); response IDs MUST match the requested ID:

```json
{"table": "incident", "sys_id": "0123456789abcdef0123456789abcdef", "record": {"sys_id": "0123456789abcdef0123456789abcdef", "number": "INC0010001", "short_description": "Email unavailable"}}
```

Error (`isError: true`):

```json
{"status": "error", "code": "PERMISSION_DENIED", "message": "Read access is denied for this operation.", "retryable": false, "outcome": "failed"}
```

### `create_task` — illustrative contract 1.0.0

Owner: service-desk maintainers. Deployment: supported local session-based MCP
only; no remote write capability is implied. Raw-query exceptions: none.

Published description:

> Prepare creation of one task using short_description, optional description,
> priority, and an optional raw assignment_group sys_id. This call makes no
> ServiceNow request and returns a complete preview valid for 600 seconds in the
> originating server/session. Show it and wait for explicit approval in the next
> user reply before confirm_pending_write. Changed values need a new preview;
> confirmation IDs are single-use. Do not automatically retry writes; reconcile
> uncertain outcomes first. Server confirmation cannot independently verify a
> human reply. Other fields, raw queries, and stateless previews are unsupported.

Validation: trim short_description and description before checking lengths;
require a nonblank summary, reject blank description when supplied, reject nulls
and unknown fields. Apply omitted priority as `"3"`; require an exact string
choice. Do not normalize assignment_group IDs; require 32 lowercase hex characters.
The illustrative 160/4000 character limits and priority choices MUST be verified
against the instance. The normalized payload MUST include priority and only
supplied optional fields. There is one preview, with no pagination.

Permissions: restrict preview access to callers authorized for the write
capability. Preview generation performs no ServiceNow lookup and does not prove
live ACL access. Confirmation uses the configured local integration identity
and MUST check its current authorization, task create/field ACLs, and the supplied
assignment group under the verified instance policy. Do not grant reference
lookup permission merely because a reference ID was supplied. Actual roles and
scopes are release prerequisites.

`create_task` returns only awaiting-confirmation or error. Cancellation, persisted
record success, and dispatched-write failures belong to `confirm_pending_write`,
whose own specification/schema MUST cover them. Its existing successful shape is
`{table, record}` and cancellation is `{status, message, preview}`; this example
does not redefine those response schemas. Follow section 4 for expiry, session
binding, restart, replay, and uncertain outcomes.

Applicable preparation errors: `VALIDATION_ERROR`, `AUTHENTICATION_REQUIRED`,
`PERMISSION_DENIED`, `RAW_QUERY_PROHIBITED`, `SESSION_REQUIRED`,
`PREVIEW_LIMIT_EXCEEDED`, `INTERNAL_ERROR`. All have `retryable: false` and
`outcome: "not_attempted"`; no ServiceNow request is made. Confirmation additionally
needs `CONFIRMATION_INVALID`, upstream/authentication/permission errors and
`TIMEOUT`, with `retryable: false` and `outcome: "unknown"` when commitment cannot
be determined.

Input schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object", "additionalProperties": false,
  "properties": {
    "short_description": {"type": "string", "minLength": 1, "maxLength": 160, "pattern": "\\S", "description": "Required summary; trim before validating."},
    "description": {"type": "string", "minLength": 1, "maxLength": 4000, "pattern": "\\S", "description": "Optional details; trim before validating; omit if unused."},
    "priority": {"type": "string", "enum": ["1", "2", "3", "4", "5"], "default": "3", "description": "Raw choice code; apply default explicitly."},
    "assignment_group": {"type": "string", "pattern": "^[0-9a-f]{32}$", "description": "Optional raw group sys_id; omit if unused."}
  },
  "required": ["short_description"]
}
```

Output schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "oneOf": [
    {
      "type": "object", "additionalProperties": false,
      "properties": {
        "status": {"const": "awaiting_confirmation", "description": "No ServiceNow write has occurred."},
        "preview_id": {"type": "string", "minLength": 1, "description": "Opaque, single-use ID bound to this server/session."},
        "preview": {
          "type": "object", "additionalProperties": false,
          "properties": {
            "operation": {"const": "insert", "description": "Proposed operation."},
            "table": {"const": "task", "description": "Target table."},
            "fields": {
              "type": "object", "additionalProperties": false,
              "properties": {
                "short_description": {"type": "string", "minLength": 1, "maxLength": 160, "pattern": "\\S", "description": "Normalized summary."},
                "description": {"type": "string", "minLength": 1, "maxLength": 4000, "pattern": "\\S", "description": "Normalized details when supplied."},
                "priority": {"type": "string", "enum": ["1", "2", "3", "4", "5"], "description": "Explicit raw priority code."},
                "assignment_group": {"type": "string", "pattern": "^[0-9a-f]{32}$", "description": "Raw group sys_id when supplied."}
              },
              "required": ["short_description", "priority"]
            }
          },
          "required": ["operation", "table", "fields"]
        },
        "expires_in_seconds": {"const": 600, "description": "Preview lifetime at creation."},
        "message": {"type": "string", "minLength": 1, "description": "Review and confirmation instructions."}
      },
      "required": ["status", "preview_id", "preview", "expires_in_seconds", "message"]
    },
    {
      "type": "object", "additionalProperties": false,
      "properties": {
        "status": {"const": "error", "description": "Preparation failure."},
        "code": {"type": "string", "enum": ["VALIDATION_ERROR", "AUTHENTICATION_REQUIRED", "PERMISSION_DENIED", "RAW_QUERY_PROHIBITED", "SESSION_REQUIRED", "PREVIEW_LIMIT_EXCEEDED", "INTERNAL_ERROR"], "description": "Stable error code."},
        "message": {"type": "string", "minLength": 1, "description": "Safe recovery message."},
        "retryable": {"const": false, "description": "Do not repeat unchanged preparation automatically."},
        "outcome": {"const": "not_attempted", "description": "No ServiceNow operation was dispatched."}
      },
      "required": ["status", "code", "message", "retryable", "outcome"]
    }
  ]
}
```

Valid arguments (priority defaults to `"3"`):

```json
{"short_description": "Track requests", "description": "Collect incoming requests."}
```

Preview (`isError: false`):

```json
{"status": "awaiting_confirmation", "preview_id": "illustrative-opaque-id", "preview": {"operation": "insert", "table": "task", "fields": {"short_description": "Track requests", "description": "Collect incoming requests.", "priority": "3"}}, "expires_in_seconds": 600, "message": "No write was made. Show the complete preview and wait for explicit approval in the next user reply before confirm_pending_write; changed values require a new preview."}
```

Preparation error (`isError: true`):

```json
{"status": "error", "code": "VALIDATION_ERROR", "message": "short_description must be nonblank after trimming.", "retryable": false, "outcome": "not_attempted"}
```

## 8. Review checklist

- [ ] Name, owner, version, published description, and supported modes are documented.
- [ ] Input/output snapshots are explicit, self-contained, versioned, and match discovery.
- [ ] Examples validate; defaults, nullability, normalized values, and result variants agree.
- [ ] Invalid IDs, unknown/nested fields, blank/oversized values, unsupported choices,
  and excessive limits are rejected before ServiceNow contact.
- [ ] Tables, fields, operators, roles/scopes, and ACL prerequisites are verified;
  unauthorized operations and inaccessible fields/records disclose no protected data.
- [ ] Raw queries and syntax hidden in filter values are blocked without an exception;
  missing, expired, revoked, and out-of-scope exceptions are rejected.
- [ ] Reads, preview creation, and confirmation have accurate side-effect descriptions.
- [ ] Preview generation makes no ServiceNow request; the complete normalized payload
  is shown and confirmation cannot replace values.
- [ ] Approval, cancellation, 600-second expiry, cross-session access, restart,
  repeated/concurrent confirmation, and capacity limits are covered by mocked checks.
- [ ] Dispatched-write timeout reports an unknown outcome, consumes the ID, and
  prohibits automatic retries; reconciliation guidance is present.
- [ ] Errors have stable codes and safe messages; `isError` and output schemas agree.
- [ ] Changelog, compatibility review, migrations, and deprecation dates are complete.
- [ ] Review records identify unresolved compliance gaps; no live writes are needed
  to validate tool contracts.

## Current compliance gaps

This is a documentation change, not enforcement or a schema migration. Current
tools MUST NOT be described as compliant merely because this standard exists.

- `common/records.py` and Agile list tools accept caller-supplied encoded `query`
  strings; `client.py` forwards them as `sysparm_query`. There is no trusted
  owner-exception gate in that path. Typed filters and a reviewed migration are needed.
- Existing Python `dict` results do not provide the explicit field-level contracts
  illustrated here. Per-tool semantic versions and released schema snapshots
  must be introduced through separate implementation work.
- Current validation, descriptions, and permission specifications need per-tool
  review; target bounds, identity checks, and choices in these examples are not
  implemented or verified against a live instance by this document.
- Current write failures return `status`/`message` (and sometimes preview/retry
  guidance), not the stable error envelope required here. MCP error flags and
  safe sanitization need verification during migration.
- Existing writes already use preview-before-confirmation with 600-second,
  single-use, session-bound IDs. This provides useful safeguards but does not
  independently verify human approval or support stateless previews.

See [architecture](architecture.md), [authentication](authentication.md), and
[write review](write-review.md) for current implementation guidance.
