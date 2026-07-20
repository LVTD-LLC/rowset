from typing import Any

from django.conf import settings
from posthog.mcp import MCPAnalyticsOptions, instrument


def _parameter_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "other"


def sanitize_mcp_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Keep MCP usage shape while removing user-owned request and response contents."""
    if event.get("event") == "$exception":
        return None

    properties = dict(event.get("properties") or {})
    parameters = properties.get("$mcp_parameters")
    arguments = None
    if isinstance(parameters, dict):
        request = parameters.get("request")
        if isinstance(request, dict):
            params = request.get("params")
            if isinstance(params, dict):
                arguments = params.get("arguments")

    if isinstance(arguments, dict):
        argument_names = sorted(str(name) for name in arguments)
        properties["$mcp_parameters"] = {
            "argument_count": len(argument_names),
            "argument_names": argument_names,
            "argument_types": {
                str(name): _parameter_type(value) for name, value in arguments.items()
            },
        }
    else:
        properties.pop("$mcp_parameters", None)

    properties.pop("$mcp_response", None)
    return {**event, "properties": properties}


def configure_mcp_analytics(server):
    if not settings.POSTHOG_API_KEY:
        return None

    return instrument(
        server,
        options=MCPAnalyticsOptions(
            context=False,
            enable_exception_autocapture=False,
            before_send=sanitize_mcp_event,
        ),
    )
