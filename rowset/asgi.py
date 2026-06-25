"""
ASGI config for rowset project.

It exposes the ASGI callable as a module-level variable named ``application``.
"""

import os

from django.core.asgi import get_asgi_application
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Mount, Route

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rowset.settings")

django_application = get_asgi_application()

from apps.mcp_server.auth import MCP_INTERNAL_PATH, MCP_MOUNT_PATH  # noqa: E402
from apps.mcp_server.server import mcp  # noqa: E402

mcp_application = mcp.http_app(
    path=MCP_INTERNAL_PATH,
    json_response=True,
    stateless_http=True,
)


def redirect_mcp(request: Request) -> RedirectResponse:
    return RedirectResponse(str(request.url.replace(path="/mcp/")), status_code=307)


application = Starlette(
    routes=[
        Route("/mcp", endpoint=redirect_mcp, methods=["GET", "POST", "DELETE"]),
        Mount(MCP_MOUNT_PATH, app=mcp_application),
        Mount("/", app=django_application),
    ],
    lifespan=mcp_application.lifespan,
)
