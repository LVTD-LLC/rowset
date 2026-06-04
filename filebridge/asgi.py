"""
ASGI config for filebridge project.

It exposes the ASGI callable as a module-level variable named ``application``.
"""

import os

from django.core.asgi import get_asgi_application
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Mount, Route

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "filebridge.settings")

django_application = get_asgi_application()

from apps.mcp_server.oauth import MCP_INTERNAL_PATH, MCP_MOUNT_PATH, mcp_auth  # noqa: E402
from apps.mcp_server.server import mcp  # noqa: E402

mcp_application = mcp.http_app(path=MCP_INTERNAL_PATH)


def redirect_mcp(request: Request) -> RedirectResponse:
    return RedirectResponse(str(request.url.replace(path="/mcp/")), status_code=307)


application = Starlette(
    routes=[
        *mcp_auth.get_well_known_routes(mcp_path=MCP_INTERNAL_PATH),
        Route("/mcp", endpoint=redirect_mcp, methods=["GET", "POST", "DELETE"]),
        Mount(MCP_MOUNT_PATH, app=mcp_application),
        Mount("/", app=django_application),
    ],
    lifespan=mcp_application.lifespan,
)
