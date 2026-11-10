from contextvars import ContextVar

# No default: MCP calls must have passed the authentication middleware.
workspace_context: ContextVar[str | None] = ContextVar("workspace_context")
