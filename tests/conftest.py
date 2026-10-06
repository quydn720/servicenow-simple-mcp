def reviewed_tools(server):
    """Exercise the explicit preview/confirm round trip in payload regression tests."""
    import asyncio
    import inspect
    from types import SimpleNamespace

    registered = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    ctx = SimpleNamespace(fastmcp=server, session_id="payload-test-session")
    def adapt(tool):
        if not inspect.iscoroutinefunction(tool.fn):
            return tool
        def invoke(*args, **kwargs):
            result = asyncio.run(tool.fn(*args, ctx=ctx, **kwargs))
            if result.get("status") == "awaiting_confirmation":
                result = asyncio.run(registered["confirm_pending_write"].fn(
                    result["preview_id"], True, ctx=ctx,
                ))
            return result
        return SimpleNamespace(fn=invoke, parameters=tool.parameters, name=tool.name)
    return {name: adapt(tool) for name, tool in registered.items()}
