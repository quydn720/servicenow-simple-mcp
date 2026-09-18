from __future__ import annotations

from typing import Any, List, Optional

from fastmcp import FastMCP
from app.tools import ClientFactory


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool()
    def list_records(table: str, query: Optional[str] = None, fields: Optional[List[str]] = None, limit: int = 10) -> dict:
        """List records from a ServiceNow table. Restrict to known tables and safe fieldsets in production."""
        if not table or not table.strip():
            raise ValueError("The table name is required.")
    
        allowed_tables = {"incident", "task", "sc_task", "problem", "change_request"}
        if table.lower() not in allowed_tables:
            raise ValueError(f"Table '{table}' is not allowed in this starter configuration.")
    
        client = client_factory()
        records = client.list_records(table=table, query=query, fields=fields, limit=limit)
        return {"table": table, "count": len(records), "records": records}

    @mcp.tool()
    def get_record(table: str, sys_id: str, fields: Optional[List[str]] = None) -> dict:
        """Fetch a single ServiceNow record by sys_id."""
        if not table or not table.strip():
            raise ValueError("The table name is required.")
        if not sys_id or not sys_id.strip():
            raise ValueError("The sys_id is required.")
    
        allowed_tables = {"incident", "task", "sc_task", "problem", "change_request"}
        if table.lower() not in allowed_tables:
            raise ValueError(f"Table '{table}' is not allowed in this starter configuration.")
    
        client = client_factory()
        record = client.get_record(table=table, sys_id=sys_id, fields=fields)
        return {"table": table, "sys_id": sys_id, "record": record}
