"""FastMCP server wiring: auth gate, HTTP lifespan, tool registration, entrypoint.

The server speaks the Streamable HTTP transport (``transport="http"``) and is
intended to run as a Docker container. The MCP endpoint is gated by a static
bearer token; the Mealie credential itself is provided per request (see
``client.py``).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import client, tools
from .config import MEALIE_TOKEN_HEADER, Settings

INSTRUCTIONS = f"""\
Read-only access to a Mealie recipe and meal-planning instance.

Authentication: every request must include two things —
  1. 'Authorization: Bearer <MCP token>' to reach this server, and
  2. '{MEALIE_TOKEN_HEADER}: <your Mealie API token>' so the server can act as you in Mealie.

Use search_recipes to find recipes and get_recipe for full detail. Reference
data (categories, tags, tools, foods, units) and household data (shopping lists,
meal plans, cookbooks) are exposed through their own tools. Write tools
(create/update/delete) are available only when the server runs with writes
enabled; the Mealie token's own permissions are always enforced as well.
"""


def build_server(settings: Settings) -> FastMCP:
    """Construct the FastMCP server for the given settings."""

    verifier = StaticTokenVerifier(
        tokens={
            token: {"client_id": f"mcp-client-{i}", "scopes": []}
            for i, token in enumerate(settings.auth_tokens)
        }
    )

    @contextlib.asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[None]:
        http_client = httpx.AsyncClient(
            timeout=settings.request_timeout,
            verify=settings.verify_ssl,
            follow_redirects=True,
        )
        client.configure(http_client, settings)
        try:
            yield
        finally:
            client.shutdown()
            await http_client.aclose()

    mcp = FastMCP(
        name="mealie-mcp",
        instructions=INSTRUCTIONS,
        version="0.2.0",
        auth=verifier,
        lifespan=lifespan,
    )

    tools.register(mcp, include_writes=not settings.read_only)

    # Unauthenticated liveness probe for Docker / reverse proxies. Custom routes
    # are not behind the MCP auth gate, so this stays reachable without a token.
    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return mcp


def main() -> None:
    settings = Settings.from_env()
    mcp = build_server(settings)
    mcp.run(
        transport="http",
        host=settings.host,
        port=settings.port,
        path=settings.path,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
