"""Published knowledge summary search for service-desk workflows."""

from fastmcp import FastMCP
from servicenow_mcp.tools import ClientFactory
from servicenow_mcp.tools.contracts import (
    KNOWLEDGE_FIELDS,
    Limit,
    READ_RESULTS,
    SysId,
    contract_tool,
    project_records,
)
from .search import SearchText, SEARCH_LIMITATIONS


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @contract_tool(
        mcp,
        READ_RESULTS["knowledge", "list"],
        description="Search kb_knowledge summaries by a literal short_description substring when finding published articles. "
        "Only active articles with workflow_state=published are requested; optional knowledge_base restricts by raw kb_knowledge_base sys_id. "
        "Supported/default fields: "
        + ", ".join(KNOWLEDGE_FIELDS)
        + ". sys_id is raw, kb_knowledge_base is a display name, "
        "other values are raw strings; unavailable fields may be omitted. No article bodies, attachments, drafts, or knowledge writes. "
        "This Table API search relies on the execution identity's table/field ACLs; it does not independently enforce "
        "portal user criteria or filter valid_to dates. " + SEARCH_LIMITATIONS,
    )
    def list_knowledge_articles(
        search_text: SearchText, knowledge_base: SysId | None = None, limit: Limit = 10
    ) -> dict:
        clauses = [
            "active=true",
            "workflow_state=published",
            f"short_descriptionLIKE{search_text}",
        ]
        if knowledge_base is not None:
            clauses.append(f"kb_knowledge_base={knowledge_base}")
        records = client_factory().list_records(
            "kb_knowledge",
            query="^".join(clauses),
            fields=list(KNOWLEDGE_FIELDS),
            limit=limit,
        )
        records = project_records(records, "kb_knowledge", KNOWLEDGE_FIELDS, limit)
        return {"table": "kb_knowledge", "count": len(records), "records": records}
