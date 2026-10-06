# Agile planning

Agile tools live in `src/servicenow_mcp/tools/product_owner/agile_planning/`, with `stories.py`,
`epics.py`, and `products.py` registered through the existing `product_owner`
feature. No configuration migration is required.

| Tools | ServiceNow table | Editable fields |
| --- | --- | --- |
| `create_agile_story`, `get_agile_story`, `list_agile_stories`, `update_agile_story` | `rm_story` | short_description, description, acceptance_criteria, story_points, priority, product, epic |
| `create_agile_epic`, `get_agile_epic`, `list_agile_epics`, `update_agile_epic` | `rm_epic` | short_description, description, product, priority |
| `get_agile_product`, `list_agile_products` | `cmdb_model` | Read only |

Creation requires only a nonblank `short_description`; priority defaults to `"3"`.
Story points range from 0 to 100. Acceptance criteria supports HTML. Existing
`create_agile_story` arguments and positional order remain compatible, with
optional `product` and `epic` appended.

References accept 32-character hexadecimal ServiceNow sys_ids, not names. First
use `list_agile_products` to find the product ID and `list_agile_epics` to find an
epic ID, then pass those IDs to story creation. ServiceNow enforces reference
existence, ACLs, and business rules.

Example MCP tool arguments (replace example IDs with lookup results):

```text
list_agile_products(fields=["sys_id", "name"], limit=100)
list_agile_epics(fields=["sys_id", "short_description", "product"], limit=100)
create_agile_story(
    short_description="Allow customers to track requests",
    product="0123456789abcdef0123456789abcdef",
    epic="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    acceptance_criteria="<p>Customers can view their own request status.</p>"
)
update_agile_story(sys_id="11111111111111111111111111111111", epic="")
```

Get/update tools require a record sys_id. List tools accept `fields` and `limit`
(default 10, clamped by the client to 1–100). The legacy `query` argument MUST be
omitted or null; any string returns a `RAW_QUERY_PROHIBITED` tool error before
client creation. Structured filters and owner-approved exceptions are not
implemented. Lists are unfiltered and bounded, so they may not contain the
desired record; use get tools when a sys_id is known.
Default lookup fields include sys_id and number/short_description for stories
and epics, and sys_id/name for products. Explicit `fields` overrides the defaults.

Update fields are optional: omitted or null values leave fields unchanged;
empty strings clear optional text/reference fields. Blank short descriptions and
updates with no supplied changes are rejected. Priority is passed through using
the existing tool behavior. Write tools return previews; confirmed writes return
`{table, record}`. Gets return
`{table, sys_id, record}`; lists return `{table, count, records}`. Failed writes
are not automatically retried.

Product creation, deletion, sprints, releases, and workflow state transitions are
outside this tool set.
