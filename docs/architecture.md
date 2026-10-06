# Architecture and adding tools

`servers/stdio.py` wires configuration, a client factory, and the explicit feature
registry. `create_server(client_factory=...)` supports isolated tests. Discovery
requires neither ServiceNow credentials nor a network connection. Credentials
are validated when a tool requests its client.

The `src/servicenow_mcp/auth` providers implement `authenticate(session)`; the factory selects
Basic or OAuth. `ServiceNowClient` owns HTTP and Table API operations. Feature
modules in `src/servicenow_mcp/tools` own use-case validation, payloads, and MCP results.

To add a use case:

Follow the [MCP tool design standard](mcp-tool-design-standard.md) and complete
its tool specification template before adding or changing a tool. See its
versioning rules for breaking changes and its checklist for review requirements.

1. Add a module to the appropriate feature package, exporting
   `register(mcp, client_factory)`.
2. Define tools inside that function with `@mcp.tool()`, obtain the client through
   `client_factory()`, and call its API methods. Do not import `servicenow_mcp.servers.stdio` or
   access credentials from tools.
3. Call the module's registration function from its feature package's `register`.
   A new feature also needs an explicit entry in the registry and `KNOWN_FEATURES`.
4. Add mocked tests for discovery, inputs, payloads, and responses. Preserve
   existing MCP names and schemas when extending current use cases.

The developer package is an extension point only. Incident updates and catalog
modifications are not implemented.
