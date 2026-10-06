from __future__ import annotations

from fastmcp import FastMCP
from servicenow_mcp.tools import ClientFactory
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


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @contract_tool(mcp, READ_RESULTS["common", "list"])
    def list_records(
        table: Table,
        query: RawQuery = None,
        fields: CommonFields | None = None,
        limit: Limit = 10,
    ) -> dict:
        """Read up to 1–100 records (default 10) from incident, task, sc_task, problem, or change_request. Only declared common fields are supported; sys_id is always included and reference fields use display names. No pagination or writes. Raw queries are prohibited: omit query or pass null; filters and exceptions are not implemented."""
        reject_raw_query(query)
        selected = select_fields(fields, COMMON_FIELDS)
        records = client_factory().list_records(
            table=table, query=None, fields=selected, limit=limit
        )
        records = project_records(records, table, selected, limit)
        return {"table": table, "count": len(records), "records": records}

    @contract_tool(mcp, READ_RESULTS["common", "get"])
    def get_record(
        table: Table, sys_id: SysId, fields: CommonFields | None = None
    ) -> dict:
        """Read one record by raw sys_id from incident, task, sc_task, problem, or change_request. Only declared common fields are supported; sys_id is always included and references use display names. No writes or pagination. Transient read failures may be retried."""
        selected = select_fields(fields, COMMON_FIELDS)
        record = project_record(
            client_factory().get_record(table=table, sys_id=sys_id, fields=selected),
            table,
            selected,
        )
        if record["sys_id"].lower() != sys_id.lower():
            raise ValueError("ServiceNow returned a different record identifier.")
        return {"table": table, "sys_id": sys_id, "record": record}
