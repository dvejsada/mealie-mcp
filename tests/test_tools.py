"""Tests for tool registration and end-to-end tool execution.

End-to-end tests drive the server through FastMCP's in-memory client; the
``configured`` fixture supplies a fake authenticated request and respx mocks the
Mealie responses.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastmcp import Client

from mealie_mcp.config import Settings
from mealie_mcp.server import build_server
from tests.conftest import BASE_URL

READ_TOOLS = {
    "search_recipes", "get_recipe", "get_recipe_suggestions",
    "list_categories", "list_tags", "list_tools", "list_foods",
    "list_units", "list_cookbooks", "get_shopping_lists", "get_shopping_list",
    "get_meal_plan", "get_todays_meals", "get_current_user", "get_app_info",
}
WRITE_TOOLS = {
    "create_recipe_from_url", "create_recipe", "update_recipe", "delete_recipe",
    "mark_recipe_made", "add_shopping_item", "set_shopping_item_checked",
    "add_recipe_to_shopping_list", "create_mealplan_entry", "delete_mealplan_entry",
}


def _server(read_only: bool):
    return build_server(
        Settings(auth_tokens=["t"], mealie_base_url=BASE_URL, read_only=read_only)
    )


async def _tool_names(read_only: bool) -> set[str]:
    async with Client(_server(read_only)) as c:
        return {t.name for t in await c.list_tools()}


async def test_readonly_registers_only_read_tools():
    names = await _tool_names(read_only=True)
    assert names == READ_TOOLS
    assert names.isdisjoint(WRITE_TOOLS)


async def test_write_mode_adds_write_tools():
    names = await _tool_names(read_only=False)
    assert READ_TOOLS <= names
    assert WRITE_TOOLS <= names


async def test_search_recipes_returns_trimmed_summaries(configured):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/recipes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "slug": "soup",
                            "name": "Soup",
                            "tags": [{"name": "easy"}],
                            "recipeCategory": [{"name": "Dinner"}],
                            "recipeInstructions": [{"text": "boil"}],
                        }
                    ],
                    "page": 1,
                    "per_page": 50,
                    "total": 1,
                    "total_pages": 1,
                },
            )
        )
        async with Client(_server(read_only=True)) as c:
            result = await c.call_tool("search_recipes", {"search": "soup"})

    data = result.data
    assert data["total"] == 1
    item = data["items"][0]
    assert item["tags"] == ["easy"]
    assert item["categories"] == ["Dinner"]
    assert "recipeInstructions" not in item  # trimmed out


async def test_create_recipe_posts_expected_body(configured):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/recipes").mock(
            return_value=httpx.Response(201, json="stew")
        )
        async with Client(_server(read_only=False)) as c:
            await c.call_tool("create_recipe", {"name": "Stew"})

    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "Stew"}


async def test_write_tool_absent_in_readonly_mode(configured):
    async with Client(_server(read_only=True)) as c:
        with pytest.raises(Exception):  # tool not found
            await c.call_tool("create_recipe", {"name": "Stew"})
