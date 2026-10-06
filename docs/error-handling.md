# Standard tool error handling

Every registered tool returns execution errors in `structuredContent` with MCP
`isError: true`. Text content also contains the serialized error object.
All output schemas include the error variant, including read tools and failures
from argument validation before a tool body runs. Unknown or unavailable tools
return JSON-RPC error -32602 with a safe message. Malformed protocol requests and
transport authentication remain the responsibility of the MCP framework.

```json
{
  "status": "error",
  "code": "TIMEOUT",
  "message": "ServiceNow did not return a definitive response before the deadline.",
  "retryable": false,
  "outcome": "unknown"
}
```

Required fields are `status`, `code`, `message`, `retryable`, and `outcome`.
Optional fields are `http_status` (an integer HTTP status), a typed saved `preview`,
and `retry_guidance` for consumed write previews. Unknown fields are forbidden.
Definitions live in `errors.py`; tool publication and MCP signaling are handled
by `tools/contracts.py`. Application code raises `OperationError` with an
explicit classification instead of relying on parsing exception text.

## Codes and recovery

| Code | Trigger / recovery |
| --- | --- |
| `VALIDATION_ERROR` | Invalid or missing arguments, unknown fields, or invalid cross-field values. Correct arguments. |
| `AUTHENTICATION_REQUIRED` | Missing credentials, rejected OAuth credentials, or API HTTP 401. Restore authentication. |
| `PERMISSION_DENIED` | Server access policy or API HTTP 403. Verify access; never bypass ACLs. |
| `NOT_FOUND` | API HTTP 404 or unavailable record. Message deliberately does not distinguish inaccessible records. |
| `RAW_QUERY_PROHIBITED` | Any supplied raw-query string. Omit query or pass null; exceptions are not implemented. |
| `CONFIRMATION_INVALID` | Unknown, expired, consumed, or foreign-session preview. Prepare and review a new preview. |
| `SESSION_REQUIRED` | Stateless preview connection. Reconnect with the supported session mode. |
| `PREVIEW_LIMIT_EXCEEDED` | Pending preview capacity reached. Cancel a preview or wait. |
| `UPSTREAM_ERROR` | Other upstream HTTP failures, connection errors, or malformed responses. Check service availability. |
| `TIMEOUT` | Connection/read timeout, or API HTTP 408/504. Apply outcome-specific recovery below. |
| `INTERNAL_ERROR` | Unexpected implementation failure or invalid tool result. Contact the tool owner. |

The classifier does not infer codes from free-text upstream errors. HTTP 401/403/404
have explicit mappings; HTTP 408/504 map to timeout. Messages come from controlled
templates. HTTP status may be disclosed, but raw upstream bodies, error.message,
error.detail, headers, validation values, stack traces, and arbitrary exception
messages are not included in output or tool-error logs. Saved previews contain
only the saved preview payload and are not populated from error bodies.

## Outcomes and retry rules

- `not_attempted`: no ServiceNow record operation was dispatched. Includes input
  validation, policy rejection, preview errors, authentication during client
  creation, known connection-establishment timeout, and invalid request URL.
- `failed`: definitive failure. Includes rejected record requests with HTTP
  400/401/403/404/429 and unsuccessful reads.
- `unknown`: a dispatched write may have committed. Includes read-response
  timeouts or connection loss during a write, HTTP 408/server/gateway failures,
  malformed write responses, and unexpected failure after write dispatch.

`retryable` means an unchanged call is safe and potentially useful to repeat;
it does not initiate an automatic retry. Transient read connection/timeout,
HTTP 429, and server/gateway failures may be retryable. Validation and access
errors are not. Write confirmation always returns `retryable: false`, even if
authentication failed before dispatch.

Confirmation consumes the preview before attempting the operation. After a known
failure, resolve the cause and prepare/approve a new preview. After an unknown
outcome, verify the instance first; never replay the consumed ID or automatically
resubmit the business request. This applies to both inserts and updates.

## Client migration and verification

Successful read, preview, cancellation, and saved-write shapes are unchanged.
Write errors previously returned `status: "error"` with `isError: false`; they
now have required code/retry/outcome fields and `isError: true`. Raw-query errors
now include structured content as well as text. Read execution errors are also
structured rather than opaque exceptions.

FastMCP Python clients throw by default on a tool error. To inspect a failure,
call with `raise_on_error=False`, check `result.is_error`, and read
`result.structured_content`. Never treat a failed confirmation as a successful
write because it contains a preview. Plain application calls to registered tool
functions also return the standard error object.

Mocked tests cover schemas and flags across all tools, HTTP status mapping,
timeouts/connection failures, safe output/logging, preview capacity/session
errors, replay prevention, known failures, unknown outcomes, and no automatic
write retries. No live ServiceNow calls are needed for these checks.

The project server adapts FastMCP 4.0.5's unknown-tool result into a JSON-RPC
protocol error and omits raw tool arguments from its server DEBUG request log.
Transport authentication failures occur before the tool boundary and are not
fabricated as tool-execution results.
