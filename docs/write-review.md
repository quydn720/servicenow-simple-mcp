# Required review before ServiceNow writes

Every current insert and update tool validates its inputs and returns a preview
without contacting ServiceNow:

```json
{
  "status": "awaiting_confirmation",
  "preview_id": "<single-use ID>",
  "preview": {
    "operation": "insert",
    "table": "rm_story",
    "fields": {"short_description": "Track requests", "priority": "3"}
  },
  "expires_in_seconds": 600,
  "message": "..."
}
```

Claude must show the complete preview, ask you to approve it, and wait for your
next reply. After approval, Claude calls
`confirm_pending_write(preview_id="<ID>", confirmed=true)`. If rejected, it
calls the same tool with `confirmed=false`, which discards the preview and
returns `{status: "cancelled", message, preview}` without a write. If you change
the fields, Claude must prepare a new preview and ask again. The initial request
to create/update a record is not approval of the resulting preview.

This uses ordinary MCP tool calls, so Claude Desktop needs no elicitation
support. Server instructions and tool descriptions tell Claude to wait for
explicit user approval. The server enforces preview-before-write and exact
saved values, but cannot independently verify that an assistant's `confirmed`
argument came from a human chat reply. This is conversational confirmation,
not a server-verified user interaction.

Preview IDs expire after 10 minutes, belong to the originating server/session,
and can be used only once. Confirmation accepts no replacement fields. IDs are
consumed before attempting the API call, including on failure, to prevent
replayed or concurrent duplicate writes. Restarting the MCP server discards all
pending previews. This server targets local stdio session-based MCP connections;
stateless protocol connections receive an error instead of a preview. With
FastMCP 4's Python client, use `mode="legacy"` to preserve the session.

Updates show the target `sys_id` and the fields to change, without fetching a
full record. Instance defaults and business rules may affect the saved record
returned by ServiceNow. The shared `confirm_pending_write` tool is registered
when either `service_desk` or `product_owner` is enabled.

Validation, authentication, and API failures return `{status: "error", message}`
(plus the preview when available). API errors include the HTTP status and
ServiceNow's structured `error.message` and `error.detail` when available,
without dumping raw response bodies or headers. Successful confirmations return
`{table, record}`. Failed writes are not automatically retried; after a
connectivity failure, check the instance before preparing a new preview because
the server might already have committed the record.

When adding a write tool, use `@return_write_errors` and route the validated
payload through `await preview_write(...)` from `src/servicenow_mcp/tools/write_review.py`.
Do not call the client's insert or update methods directly from tools.
