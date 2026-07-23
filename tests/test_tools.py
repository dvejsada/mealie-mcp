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
    "search_recipes", "get_recipe", "get_recipe_suggestions", "get_random_recipe",
    "list_categories", "list_tags", "list_tools", "list_foods",
    "list_units", "list_cookbooks", "list_labels", "get_shopping_lists",
    "get_shopping_list", "get_meal_plan", "get_todays_meals", "get_current_user",
    "get_app_info",
}
WRITE_TOOLS = {
    "create_recipe_from_url", "create_recipe", "update_recipe", "delete_recipe",
    "mark_recipe_made", "add_shopping_item", "add_shopping_items",
    "set_shopping_item_checked", "add_recipe_to_shopping_list",
    "create_mealplan_entry", "update_mealplan_entry", "delete_mealplan_entry",
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


async def test_get_recipe_trims_internal_fields_by_default(configured):
    full = {
        "id": "r1",
        "slug": "soup",
        "name": "Soup",
        "recipeIngredient": [
            {
                "quantity": 1,
                "unit": {"name": "cup"},
                "food": {"name": "water"},
                "note": "",
                "display": "1 cup water",
                "referenceId": "drop-me",
            }
        ],
        "recipeInstructions": [{"id": "i1", "title": "", "text": "boil"}],
        "settings": {"showNutrition": True},
        "comments": [{"text": "yum"}],
        "tags": [{"name": "easy"}],
    }
    with respx.mock:
        respx.get(f"{BASE_URL}/api/recipes/soup").mock(
            return_value=httpx.Response(200, json=full)
        )
        async with Client(_server(read_only=True)) as c:
            trimmed = (await c.call_tool("get_recipe", {"slug": "soup"})).data
            raw = (
                await c.call_tool(
                    "get_recipe", {"slug": "soup", "include_internal": True}
                )
            ).data

    assert "settings" not in trimmed
    assert "comments" not in trimmed
    assert trimmed["recipeIngredient"][0] == {
        "quantity": 1,
        "unit": "cup",
        "food": "water",
        "note": "",
        "display": "1 cup water",
        "title": None,
    }
    assert trimmed["recipeInstructions"][0] == {"title": "", "text": "boil"}
    assert trimmed["tags"] == ["easy"]
    # include_internal returns the object untouched.
    assert raw["settings"] == {"showNutrition": True}
    assert raw["comments"] == [{"text": "yum"}]


async def test_add_shopping_item_resolves_food_name(configured):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/foods").mock(
            return_value=httpx.Response(
                200, json={"items": [{"id": "food-1", "name": "Beans"}]}
            )
        )
        route = respx.post(f"{BASE_URL}/api/households/shopping/items").mock(
            return_value=httpx.Response(201, json={"id": "item-1"})
        )
        async with Client(_server(read_only=False)) as c:
            await c.call_tool(
                "add_shopping_item",
                {"shopping_list_id": "L1", "note": "beans", "food": "beans"},
            )

    body = json.loads(route.calls.last.request.content)
    assert body["foodId"] == "food-1"
    assert body["isFood"] is True
    assert body["shoppingListId"] == "L1"


async def test_add_shopping_items_posts_array_to_bulk(configured):
    with respx.mock:
        route = respx.post(
            f"{BASE_URL}/api/households/shopping/items/create-bulk"
        ).mock(return_value=httpx.Response(201, json=[]))
        async with Client(_server(read_only=False)) as c:
            await c.call_tool(
                "add_shopping_items",
                {
                    "shopping_list_id": "L1",
                    "items": [{"note": "eggs"}, {"note": "milk", "quantity": 2}],
                },
            )

    body = json.loads(route.calls.last.request.content)
    assert isinstance(body, list)
    assert len(body) == 2
    assert body[0]["note"] == "eggs"
    assert body[1]["quantity"] == 2
    assert all(item["shoppingListId"] == "L1" for item in body)


async def test_mark_recipe_made_resolves_id_and_puts(configured):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/recipes/soup").mock(
            return_value=httpx.Response(200, json={"id": "rid-9", "slug": "soup"})
        )
        route = respx.put(f"{BASE_URL}/api/recipes/rid-9/last-made").mock(
            return_value=httpx.Response(200, json={"id": "rid-9"})
        )
        async with Client(_server(read_only=False)) as c:
            await c.call_tool(
                "mark_recipe_made",
                {"slug": "soup", "timestamp": "2026-06-29T12:00:00+00:00"},
            )

    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"timestamp": "2026-06-29T12:00:00+00:00"}


async def test_mark_recipe_made_errors_when_recipe_has_no_id(configured):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/recipes/ghost").mock(
            return_value=httpx.Response(200, json={"slug": "ghost"})  # no "id"
        )
        last_made = respx.put(url__regex=rf"{BASE_URL}/api/recipes/.+/last-made").mock(
            return_value=httpx.Response(200, json={})
        )
        async with Client(_server(read_only=False)) as c:
            with pytest.raises(Exception) as excinfo:
                await c.call_tool("mark_recipe_made", {"slug": "ghost"})

    assert "did not return an ID" in str(excinfo.value)
    assert not last_made.called  # never PUTs to /api/recipes/None/last-made


async def test_update_mealplan_entry_merges_current_entry(configured):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/households/mealplans/7").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 7,
                    "groupId": "g1",
                    "userId": "u1",
                    "date": "2026-07-24",
                    "entryType": "dinner",
                    "title": "",
                    "text": "old note",
                    "recipeId": "rid-old",
                },
            )
        )
        route = respx.put(f"{BASE_URL}/api/households/mealplans/7").mock(
            return_value=httpx.Response(200, json={"id": 7})
        )
        async with Client(_server(read_only=False)) as c:
            await c.call_tool(
                "update_mealplan_entry",
                {"entry_id": "7", "entry_type": "lunch", "recipe_id": "rid-new"},
            )

    assert route.called
    body = json.loads(route.calls.last.request.content)
    # Changed fields applied; identifiers and untouched fields preserved.
    assert body["entryType"] == "lunch"
    assert body["recipeId"] == "rid-new"
    assert body["date"] == "2026-07-24"
    assert body["text"] == "old note"
    assert body["id"] == 7
    assert body["groupId"] == "g1"
    assert body["userId"] == "u1"


async def test_add_shopping_item_prefers_exact_name_match(configured):
    with respx.mock:
        # The leading result has no id and is not an exact match; the exact
        # match ("beans") carries the id and must be the one chosen.
        respx.get(f"{BASE_URL}/api/foods").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"name": "Bean Sprouts"},
                        {"id": "food-2", "name": "Beans"},
                    ]
                },
            )
        )
        route = respx.post(f"{BASE_URL}/api/households/shopping/items").mock(
            return_value=httpx.Response(201, json={"id": "item-1"})
        )
        async with Client(_server(read_only=False)) as c:
            await c.call_tool(
                "add_shopping_item",
                {"shopping_list_id": "L1", "note": "beans", "food": "beans"},
            )

    body = json.loads(route.calls.last.request.content)
    assert body["foodId"] == "food-2"
