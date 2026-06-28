"""End-to-end tests over the real Streamable HTTP stack.

Unlike the other suites (which monkeypatch ``get_http_request`` or use the
in-memory client), these drive the actual ASGI app — auth gate, middleware and
all — so they exercise FastMCP's real header plumbing. The MCP client talks to
the app in-process via ``httpx.ASGITransport`` (no real socket); ``respx`` mocks
only the outbound Mealie calls and passes the in-process MCP traffic through.

This is the regression guard for "FastMCP drops the Authorization header": it
asserts the static gate is enforced *and* that the per-request Mealie token is
forwarded to Mealie rather than being stripped along the way.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from mealie_mcp.config import Settings
from mealie_mcp.server import build_server

GATE_TOKEN = "GATE-SECRET"
MEALIE_TOKEN = "MEALIE-USER-TOKEN"
MEALIE_BASE = "https://mealie.test"
MCP_HOST = "mcp.test"
MCP_URL = f"http://{MCP_HOST}/mcp"


def _all_messages(exc: BaseException) -> str:
    """Flatten an exception (incl. ExceptionGroup/cause/context) to one string.

    The MCP client surfaces transport errors wrapped in an ``ExceptionGroup``
    from its anyio TaskGroup, so the interesting message (e.g. a 401) is nested.
    """
    seen: set[int] = set()
    parts: list[str] = []

    def walk(e: BaseException | None) -> None:
        if e is None or id(e) in seen:
            return
        seen.add(id(e))
        parts.append(str(e))
        for sub in getattr(e, "exceptions", ()):  # ExceptionGroup members
            walk(sub)
        walk(e.__cause__)
        walk(e.__context__)

    walk(exc)
    return " | ".join(parts)


@contextlib.asynccontextmanager
async def http_client(
    *,
    gate_token: str = GATE_TOKEN,
    mealie_token: str | None = MEALIE_TOKEN,
    mealie_url: str | None = None,
) -> AsyncIterator[Client]:
    """Yield a FastMCP client connected to the real app over ASGITransport.

    Must be used inside a ``respx`` block that passes the ``mcp.test`` host
    through (otherwise the in-process MCP traffic would be intercepted too).
    """
    settings = Settings(auth_tokens=[GATE_TOKEN], mealie_base_url=MEALIE_BASE)
    app = build_server(settings).http_app()

    # NOTE: `app.router.lifespan_context` and `StreamableHttpTransport`'s
    # `httpx_client_factory` are FastMCP/Starlette internals rather than
    # documented public API. They are stable for the pinned `fastmcp==3.4.2`
    # (see pyproject.toml); revisit these two lines when bumping that pin.
    def factory(headers=None, timeout=None, auth=None, **_kwargs):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            headers=headers,
            timeout=timeout,
            auth=auth,
            base_url=f"http://{MCP_HOST}",
        )

    client_headers = {"Authorization": f"Bearer {gate_token}"}
    if mealie_token is not None:
        client_headers["X-Mealie-Token"] = mealie_token
    if mealie_url is not None:
        client_headers["X-Mealie-Url"] = mealie_url

    transport = StreamableHttpTransport(
        url=MCP_URL, headers=client_headers, httpx_client_factory=factory
    )

    async with app.router.lifespan_context(app):
        async with Client(transport) as client:
            yield client


async def test_gate_accepts_token_and_forwards_mealie_token():
    """The Authorization gate lets a valid token through, and the per-request
    Mealie token reaches Mealie as a bearer token (i.e. is not dropped)."""
    with respx.mock(assert_all_called=False) as router:
        router.route(host=MCP_HOST).pass_through()
        mealie = router.get(f"{MEALIE_BASE}/api/app/about").mock(
            return_value=httpx.Response(200, json={"version": "9.9.9"})
        )
        async with http_client() as client:
            result = await client.call_tool("get_app_info", {})

    assert result.data == {"version": "9.9.9"}
    assert mealie.called
    assert mealie.calls.last.request.headers["authorization"] == f"Bearer {MEALIE_TOKEN}"


async def test_gate_rejects_invalid_token():
    """A wrong Authorization token is rejected by the static gate (401)."""
    with respx.mock(assert_all_called=False) as router:
        router.route(host=MCP_HOST).pass_through()
        with pytest.raises(BaseException) as excinfo:
            async with http_client(gate_token="WRONG-TOKEN"):
                pass
    messages = _all_messages(excinfo.value).lower()
    assert "401" in messages or "unauthorized" in messages


async def test_missing_mealie_token_surfaces_tool_error():
    """A valid gate but no X-Mealie-Token yields an actionable tool error,
    without ever calling Mealie."""
    with respx.mock(assert_all_called=False) as router:
        router.route(host=MCP_HOST).pass_through()
        async with http_client(mealie_token=None) as client:
            with pytest.raises(BaseException) as excinfo:
                await client.call_tool("get_app_info", {})
    assert "Missing Mealie credential" in _all_messages(excinfo.value)


async def test_whitespace_mealie_token_treated_as_missing():
    """A whitespace-only X-Mealie-Token is treated as missing — no Mealie call."""
    with respx.mock(assert_all_called=False) as router:
        router.route(host=MCP_HOST).pass_through()
        mealie = router.get(f"{MEALIE_BASE}/api/app/about").mock(
            return_value=httpx.Response(200, json={"version": "9.9.9"})
        )
        async with http_client(mealie_token="   ") as client:
            with pytest.raises(BaseException) as excinfo:
                await client.call_tool("get_app_info", {})
    assert "Missing Mealie credential" in _all_messages(excinfo.value)
    assert not mealie.called
