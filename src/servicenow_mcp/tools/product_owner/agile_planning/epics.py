from fastmcp import Context, FastMCP
from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.tools.contracts import (
    Summary,
    Text,
    Priority,
    SysId,
    ClearableSysId,
    PREPARE_RESULTS,
    contract_tool,
)
from servicenow_mcp.tools.descriptions import prepare_description
from servicenow_mcp.tools.write_review import preview_write, return_write_errors
from .shared import reference, register_reads, title, update_payload


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    register_reads(
        mcp,
        client_factory,
        "epic",
        "epics",
        "rm_epic",
        [
            "sys_id",
            "number",
            "short_description",
            "description",
            "product",
            "priority",
        ],
    )

    @contract_tool(
        mcp,
        PREPARE_RESULTS["rm_epic", "insert"],
        description=prepare_description(
            "rm_epic",
            ("short_description", "description", "product", "priority"),
            update=False,
            details="short_description is trimmed, nonblank and limited to 160 characters. Text fields are trimmed and limited to 4000 characters. Priority accepts raw choice codes 1–5. Priority defaults to 3. Product requires a raw sys_id. ",
        ),
    )
    @return_write_errors
    async def create_agile_epic(
        short_description: Summary,
        description: Text | None = None,
        product: SysId | None = None,
        priority: Priority = "3",
        *,
        ctx: Context,
    ) -> dict:
        payload = {"short_description": title(short_description), "priority": priority}
        if description is not None:
            payload["description"] = description.strip()
        if product is not None:
            payload["product"] = reference(product, "product")
        return await preview_write(ctx, client_factory, "rm_epic", payload)

    @contract_tool(
        mcp,
        PREPARE_RESULTS["rm_epic", "update"],
        description=prepare_description(
            "rm_epic",
            ("short_description", "description", "product", "priority"),
            update=True,
            details="short_description is trimmed, nonblank and limited to 160 characters. Text fields are trimmed and limited to 4000 characters. Priority accepts raw choice codes 1–5. Product requires a raw sys_id. ",
        ),
    )
    @return_write_errors
    async def update_agile_epic(
        sys_id: SysId,
        short_description: Summary | None = None,
        description: Text | None = None,
        product: ClearableSysId | None = None,
        priority: Priority | None = None,
        *,
        ctx: Context,
    ) -> dict:
        sys_id = reference(sys_id, "sys_id")
        payload = update_payload(
            short_description=short_description,
            description=description,
            product=product,
            priority=priority,
        )
        return await preview_write(
            ctx, client_factory, "rm_epic", payload, sys_id=sys_id
        )
