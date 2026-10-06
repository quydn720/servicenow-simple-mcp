from __future__ import annotations

from fastmcp import FastMCP
from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.errors import OperationError
from servicenow_mcp.tools.contracts import (
    CommonFields,
    Limit,
    RawQuery,
    READ_RESULTS,
    SysId,
    Table,
    COMMON_FIELDS,
    contract_tool,
    project_record,
    project_records,
    select_fields,
)
from servicenow_mcp.tools.query_policy import reject_raw_query
from servicenow_mcp.tools.descriptions import read_description


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @contract_tool(
        mcp,
        READ_RESULTS["common", "list"],
        description=read_description(
            "incident, task, sc_task, problem, change_request",
            COMMON_FIELDS,
            collection=True,
        ),
    )
    def list_records(
        table: Table,
        query: RawQuery = None,
        fields: CommonFields | None = None,
        limit: Limit = 10,
    ) -> dict:
        reject_raw_query(query)
        selected = select_fields(fields, COMMON_FIELDS)
        records = client_factory().list_records(
            table=table, query=None, fields=selected, limit=limit
        )
        records = project_records(records, table, selected, limit)
        return {"table": table, "count": len(records), "records": records}

    @contract_tool(
        mcp,
        READ_RESULTS["common", "get"],
        description=read_description(
            "incident, task, sc_task, problem, change_request",
            COMMON_FIELDS,
            collection=False,
        ),
    )
    def get_record(
        table: Table, sys_id: SysId, fields: CommonFields | None = None
    ) -> dict:
        selected = select_fields(fields, COMMON_FIELDS)
        record = project_record(
            client_factory().get_record(table=table, sys_id=sys_id, fields=selected),
            table,
            selected,
        )
        if record["sys_id"].lower() != sys_id.lower():
            raise OperationError("UPSTREAM_ERROR", outcome="failed")
        return {"table": table, "sys_id": sys_id, "record": record}
