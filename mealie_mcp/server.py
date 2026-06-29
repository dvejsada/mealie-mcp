"""FastMCP server wiring: auth gate, HTTP lifespan, tool registration, entrypoint.

The server speaks the Streamable HTTP transport (``transport="http"``) and is
intended to run as a Docker container. The MCP endpoint is gated by a static
bearer token; the Mealie credential itself is provided per request (see
``client.py``).
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
from collections.abc import AsyncIterator

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import client, tools
from .config import MEALIE_TOKEN_HEADER, Settings

logger = logging.getLogger("mealie_mcp.auth")

def _instructions(read_only: bool) -> str:
    """Server instructions, worded to match the actual read/write mode."""
    access = "Read-only access" if read_only else "Read and write access"
    writes = (
        "Write tools (create/update/delete) are not enabled on this server."
        if read_only
        else (
            "Write tools (create/update/delete) are enabled; the Mealie token's "
            "own permissions are still enforced, so a read-only token cannot "
            "mutate data."
        )
    )
    return f"""\
{access} to a Mealie recipe and meal-planning instance.

Authentication: every request must include two things —
  1. 'Authorization: Bearer <MCP token>' to reach this server, and
  2. '{MEALIE_TOKEN_HEADER}: <your Mealie API token>' so the server can act as you in Mealie.

Use search_recipes to find recipes and get_recipe for full detail. Reference
data (categories, tags, tools, foods, units, labels) and household data
(shopping lists, meal plans, cookbooks) are exposed through their own tools.
{writes}
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
        instructions=_instructions(settings.read_only),
        version="0.3.0",
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


def _token_fingerprint(token: str) -> str:
    """A short, non-reversible fingerprint of a token, safe to log."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]


def _describe_authorization(scope: Scope, token_fingerprints: set[str]) -> str:
    """Summarise a request's Authorization header without revealing the token."""
    headers = {k.lower(): v for k, v in scope.get("headers") or []}
    raw = headers.get(b"authorization")
    if raw is None:
        return "absent (no Authorization header reached the server)"
    # ASGI header values are byte strings; latin-1 round-trips any byte and never
    # raises, which is all we need to read the scheme and the token's length.
    scheme, _, value = raw.decode("latin-1").partition(" ")
    value = value.strip()
    if not value:
        return f"scheme={scheme or '<none>'} <empty token>"
    fp = _token_fingerprint(value)
    matched = fp in token_fingerprints
    return (
        f"scheme={scheme or '<none>'} token_len={len(value)} "
        f"fp={fp} matches_configured={matched}"
    )


class _AuthDebugMiddleware:
    """Outermost ASGI wrapper that logs what the auth gate receives.

    Installed only when ``MCP_AUTH_DEBUG`` is set. It sits *outside* FastMCP's
    auth middleware, so it also sees requests the gate rejects with 401 — the
    whole point when troubleshooting. Tokens are never logged: only their length
    and a short SHA-256 fingerprint, which the operator can compare against the
    configured tokens' fingerprints (logged once at startup) to tell a value
    mismatch apart from a header that a proxy stripped before it arrived.
    """

    def __init__(self, app: ASGIApp, token_fingerprints: set[str]) -> None:
        self.app = app
        self.token_fingerprints = token_fingerprints

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        authorization = _describe_authorization(scope, self.token_fingerprints)
        status: dict[str, int] = {}

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        await self.app(scope, receive, _send)
        logger.info(
            "auth-debug: %s %s authorization=%s -> %s",
            scope.get("method", "?"),
            scope.get("path", "?"),
            authorization,
            status.get("code", "?"),
        )


def _configure_debug_logging() -> None:
    """Ensure auth-debug lines are emitted regardless of uvicorn's log config."""
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False


def main() -> None:
    settings = Settings.from_env()
    mcp = build_server(settings)

    if settings.auth_debug:
        # Wrap the app in our own outermost ASGI layer so we can log what the
        # auth gate receives (FastMCP's auth middleware is opaque on 401). This
        # means serving via uvicorn directly instead of mcp.run().
        import uvicorn

        _configure_debug_logging()
        fingerprints = {_token_fingerprint(t) for t in settings.auth_tokens}
        logger.info(
            "auth-debug enabled: accepting %d token(s) with fingerprints %s",
            len(fingerprints),
            sorted(fingerprints),
        )
        app = _AuthDebugMiddleware(
            mcp.http_app(path=settings.path), token_fingerprints=fingerprints
        )
        uvicorn.run(
            app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level,
        )
        return

    mcp.run(
        transport="http",
        host=settings.host,
        port=settings.port,
        path=settings.path,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
