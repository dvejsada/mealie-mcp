"""Tests for the Mealie HTTP client: auth resolution and error translation."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from mealie_mcp import client as mclient
from tests.conftest import BASE_URL


async def test_get_success(configured):
    with respx.mock:
        route = respx.get(f"{BASE_URL}/api/recipes").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        result = await mclient.mealie_get("/api/recipes")
    assert result == {"items": []}
    # The Mealie token from the header is forwarded as a bearer token.
    assert route.calls.last.request.headers["authorization"] == "Bearer mealie-token"


async def test_get_forwards_query_params(configured):
    with respx.mock:
        route = respx.get(f"{BASE_URL}/api/recipes").mock(
            return_value=httpx.Response(200, json={})
        )
        await mclient.mealie_get("/api/recipes", params={"search": "soup", "drop": None})
    assert route.calls.last.request.url.params["search"] == "soup"
    assert "drop" not in route.calls.last.request.url.params


async def test_missing_mealie_token_raises(configured):
    configured["headers"] = {}  # no x-mealie-token
    with pytest.raises(ToolError, match="Missing Mealie credential"):
        await mclient.mealie_get("/api/recipes")


async def test_url_override_header(configured):
    configured["headers"] = {
        "x-mealie-token": "tok",
        "x-mealie-url": "https://other.test",
    }
    with respx.mock:
        respx.get("https://other.test/api/app/about").mock(
            return_value=httpx.Response(200, json={"version": "1.0"})
        )
        result = await mclient.mealie_get("/api/app/about")
    assert result == {"version": "1.0"}


async def test_401_translated(configured):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/recipes").mock(return_value=httpx.Response(401))
        with pytest.raises(ToolError, match="rejected the API token"):
            await mclient.mealie_get("/api/recipes")


async def test_404_translated(configured):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/recipes/nope").mock(return_value=httpx.Response(404))
        with pytest.raises(ToolError, match="not found"):
            await mclient.mealie_get("/api/recipes/nope")


async def test_422_includes_detail(configured):
    with respx.mock:
        respx.post(f"{BASE_URL}/api/recipes").mock(
            return_value=httpx.Response(422, json={"detail": "bad name"})
        )
        with pytest.raises(ToolError, match="bad name"):
            await mclient.mealie_post("/api/recipes", json={"name": ""})


async def test_204_returns_none(configured):
    with respx.mock:
        respx.delete(f"{BASE_URL}/api/recipes/x").mock(return_value=httpx.Response(204))
        assert await mclient.mealie_delete("/api/recipes/x") is None


async def test_network_error_translated(configured):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/recipes").mock(
            side_effect=httpx.ConnectError("boom")
        )
        with pytest.raises(ToolError, match="Could not reach Mealie"):
            await mclient.mealie_get("/api/recipes")
