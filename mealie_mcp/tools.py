"""MCP tools exposing a Mealie instance.

Read tools are always available; write tools are registered only when the server
runs with writes enabled (see ``register``). Each tool maps to a single Mealie
REST endpoint, translating snake_case arguments to Mealie's camelCase query/body
fields. Recipe search results are trimmed to the fields most useful to an
assistant; ``get_recipe`` returns the full recipe so callers can fetch detail on
demand.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from .client import (
    mealie_delete,
    mealie_get,
    mealie_patch,
    mealie_post,
    mealie_put,
)

# Reusable annotated argument types ------------------------------------------------

Page = Annotated[int, Field(ge=1, description="1-based page number.")]
PerPage = Annotated[int, Field(ge=1, le=200, description="Items per page (max 200).")]
OrderDirection = Annotated[
    Literal["asc", "desc"],
    Field(description="Sort direction for the result set."),
]
RecipeOrderBy = Annotated[
    Literal["name", "rating", "created_at", "updated_at", "last_made"] | None,
    Field(description="Field to sort recipes by; omit for Mealie's default order."),
]
MealEntryType = Literal[
    "breakfast", "lunch", "dinner", "side", "snack", "drink", "dessert"
]

# A name passed to a filter/lookup that already looks like this is treated as an
# ID and passed straight through; anything else is resolved via a search query.
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class ShoppingItemInput(BaseModel):
    """One item for ``add_shopping_items``.

    ``food``/``unit``/``label`` accept a human name or a UUID; names are resolved
    to IDs server-side so callers never need a prior lookup call.
    """

    note: str
    quantity: float = 1
    food: str | None = None
    unit: str | None = None
    label: str | None = None


def _summarize_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    """Trim a full recipe object down to fields useful for browsing/searching."""
    return {
        "id": recipe.get("id"),
        "slug": recipe.get("slug"),
        "name": recipe.get("name"),
        "description": recipe.get("description"),
        "rating": recipe.get("rating"),
        "recipeYield": recipe.get("recipeYield"),
        "totalTime": recipe.get("totalTime"),
        "prepTime": recipe.get("prepTime"),
        "cookTime": recipe.get("cookTime"),
        "tags": [t.get("name") for t in (recipe.get("tags") or [])],
        "categories": [c.get("name") for c in (recipe.get("recipeCategory") or [])],
        "dateAdded": recipe.get("dateAdded"),
    }


def _paginated(data: dict[str, Any], items: list[Any] | None = None) -> dict[str, Any]:
    """Normalise a Mealie pagination envelope, optionally replacing the items."""
    return {
        "items": items if items is not None else data.get("items", []),
        "page": data.get("page"),
        "per_page": data.get("per_page"),
        "total": data.get("total"),
        "total_pages": data.get("total_pages"),
    }


async def _resolve_to_id(value: str, endpoint: str) -> str:
    """Resolve a human name to an entity ID, or pass a UUID straight through.

    Looks the name up via the endpoint's ``search`` query and prefers an exact
    (case-insensitive) name match, falling back to the first result. Raises a
    ToolError when nothing matches, so the caller gets an actionable message
    instead of a silently empty filter.
    """
    value = value.strip()
    if _UUID_RE.match(value):
        return value
    data = await mealie_get(endpoint, params={"search": value, "perPage": 10})
    items = data.get("items", []) if isinstance(data, dict) else []
    if not items:
        raise ToolError(f"No match found for '{value}' via {endpoint}.")
    for item in items:
        if (item.get("name") or "").strip().lower() == value.lower() and item.get("id"):
            return item["id"]
    first_id = items[0].get("id")
    if not first_id:
        raise ToolError(f"Match for '{value}' via {endpoint} had no usable ID.")
    return first_id


async def _resolve_many(values: list[str], endpoint: str) -> list[str]:
    """Resolve a list of names/IDs to IDs against a single search endpoint.

    Lookups run concurrently — for several foods/tools this is one round-trip's
    worth of latency rather than one per value.
    """
    return list(await asyncio.gather(*(_resolve_to_id(v, endpoint) for v in values)))


def _trim_ingredient(ingredient: dict[str, Any]) -> dict[str, Any]:
    food = ingredient.get("food") or {}
    unit = ingredient.get("unit") or {}
    return {
        "quantity": ingredient.get("quantity"),
        "unit": unit.get("name") if isinstance(unit, dict) else unit,
        "food": food.get("name") if isinstance(food, dict) else food,
        "note": ingredient.get("note"),
        "display": ingredient.get("display"),
        "title": ingredient.get("title"),
    }


def _trim_instruction(step: dict[str, Any]) -> dict[str, Any]:
    return {"title": step.get("title"), "text": step.get("text")}


def _trim_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    """Full recipe detail minus internal bookkeeping.

    Keeps everything needed to read/cook a recipe (ingredients, instructions,
    nutrition, notes, organizers) and drops noise that bloats the response:
    ``settings``, ``assets``, ``comments``, image hashes, owning IDs and the
    per-ingredient/instruction UUIDs.
    """
    return {
        "id": recipe.get("id"),
        "slug": recipe.get("slug"),
        "name": recipe.get("name"),
        "description": recipe.get("description"),
        "orgURL": recipe.get("orgURL"),
        "rating": recipe.get("rating"),
        "recipeServings": recipe.get("recipeServings"),
        "recipeYield": recipe.get("recipeYield"),
        "recipeYieldQuantity": recipe.get("recipeYieldQuantity"),
        "totalTime": recipe.get("totalTime"),
        "prepTime": recipe.get("prepTime"),
        "performTime": recipe.get("performTime"),
        "cookTime": recipe.get("cookTime"),
        "recipeIngredient": [
            _trim_ingredient(i) for i in (recipe.get("recipeIngredient") or [])
        ],
        "recipeInstructions": [
            _trim_instruction(s) for s in (recipe.get("recipeInstructions") or [])
        ],
        "nutrition": recipe.get("nutrition"),
        "notes": recipe.get("notes"),
        "tags": [t.get("name") for t in (recipe.get("tags") or [])],
        "categories": [c.get("name") for c in (recipe.get("recipeCategory") or [])],
        "tools": [t.get("name") for t in (recipe.get("tools") or [])],
        "extras": recipe.get("extras"),
        "dateAdded": recipe.get("dateAdded"),
        "lastMade": recipe.get("lastMade"),
    }


async def _build_shopping_item(
    shopping_list_id: str,
    note: str,
    quantity: float,
    food: str | None,
    unit: str | None,
    label: str | None,
) -> dict[str, Any]:
    """Resolve name-or-ID fields and build a Mealie shopping-item create body."""
    food_id = await _resolve_to_id(food, "/api/foods") if food else None
    unit_id = await _resolve_to_id(unit, "/api/units") if unit else None
    label_id = await _resolve_to_id(label, "/api/groups/labels") if label else None
    return {
        "shoppingListId": shopping_list_id,
        "note": note,
        "quantity": quantity,
        "foodId": food_id,
        "unitId": unit_id,
        "labelId": label_id,
        "isFood": food_id is not None,
        "checked": False,
    }


def register(mcp: FastMCP, include_writes: bool = False) -> None:
    """Register tools on the given FastMCP server.

    Read tools are always registered. Write tools (create/update/delete) are
    registered only when ``include_writes`` is True.
    """

    # --- Recipes ---------------------------------------------------------------

    @mcp.tool
    async def search_recipes(
        search: Annotated[
            str | None, Field(description="Free-text search across recipe names and content.")
        ] = None,
        categories: Annotated[
            list[str] | None,
            Field(description="Filter by category names or IDs."),
        ] = None,
        tags: Annotated[
            list[str] | None, Field(description="Filter by tag names or IDs.")
        ] = None,
        tools: Annotated[
            list[str] | None, Field(description="Filter by required tool names or IDs.")
        ] = None,
        foods: Annotated[
            list[str] | None, Field(description="Filter by ingredient/food names or IDs.")
        ] = None,
        require_all_categories: bool = False,
        require_all_tags: bool = False,
        order_by: RecipeOrderBy = None,
        order_direction: OrderDirection = "desc",
        page: Page = 1,
        per_page: PerPage = 50,
    ) -> dict[str, Any]:
        """Search and list recipes. Returns a trimmed summary for each match
        (use get_recipe with a slug for full detail)."""
        data = await mealie_get(
            "/api/recipes",
            params={
                "search": search,
                "categories": categories,
                "tags": tags,
                "tools": tools,
                "foods": foods,
                "requireAllCategories": require_all_categories,
                "requireAllTags": require_all_tags,
                "orderBy": order_by,
                "orderDirection": order_direction,
                "page": page,
                "perPage": per_page,
            },
        )
        items = [_summarize_recipe(r) for r in data.get("items", [])]
        return _paginated(data, items)

    @mcp.tool
    async def get_recipe(
        slug: Annotated[
            str,
            Field(description="Recipe slug (e.g. 'spaghetti-bolognese') or recipe ID."),
        ],
        include_internal: Annotated[
            bool,
            Field(
                description=(
                    "Return the raw Mealie object (settings, assets, comments, "
                    "owning IDs) instead of the trimmed view. Use before "
                    "update_recipe if you need the exact schema."
                )
            ),
        ] = False,
    ) -> dict[str, Any]:
        """Get a single recipe by its slug or ID: ingredients, instructions,
        nutrition, notes, tags and categories. Trimmed of internal bookkeeping by
        default; pass include_internal=True for the raw object."""
        recipe = await mealie_get(f"/api/recipes/{slug}")
        return recipe if include_internal else _trim_recipe(recipe)

    @mcp.tool
    async def get_recipe_suggestions(
        foods: Annotated[
            list[str] | None,
            Field(description="Food names or IDs you have on hand (names resolved for you)."),
        ] = None,
        tools: Annotated[
            list[str] | None,
            Field(description="Tool names or IDs you have on hand (names resolved for you)."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="Max suggestions.")] = 10,
        max_missing_foods: Annotated[
            int, Field(ge=0, description="Allowed number of missing ingredients.")
        ] = 5,
        max_missing_tools: Annotated[
            int, Field(ge=0, description="Allowed number of missing tools.")
        ] = 5,
    ) -> dict[str, Any]:
        """Suggest recipes you can make from the foods and tools you have on hand.
        Food/tool names are resolved to IDs for you, so plain names work — no
        need to call list_foods/list_tools first."""
        food_ids = await _resolve_many(foods, "/api/foods") if foods else None
        tool_ids = (
            await _resolve_many(tools, "/api/organizers/tools") if tools else None
        )
        return await mealie_get(
            "/api/recipes/suggestions",
            params={
                "foods": food_ids,
                "tools": tool_ids,
                "limit": limit,
                "maxMissingFoods": max_missing_foods,
                "maxMissingTools": max_missing_tools,
            },
        )

    @mcp.tool
    async def get_random_recipe() -> dict[str, Any]:
        """Get a single random recipe — handy for "what should I cook tonight?".
        Returns the same trimmed detail as get_recipe."""
        recipe = await mealie_get("/api/recipes/random")
        return _trim_recipe(recipe)

    # --- Organizers & reference data ------------------------------------------

    @mcp.tool
    async def list_categories(
        search: str | None = None, page: Page = 1, per_page: PerPage = 100
    ) -> dict[str, Any]:
        """List recipe categories (id, name, slug)."""
        return await mealie_get(
            "/api/organizers/categories",
            params={"search": search, "page": page, "perPage": per_page},
        )

    @mcp.tool
    async def list_tags(
        search: str | None = None, page: Page = 1, per_page: PerPage = 100
    ) -> dict[str, Any]:
        """List recipe tags (id, name, slug)."""
        return await mealie_get(
            "/api/organizers/tags",
            params={"search": search, "page": page, "perPage": per_page},
        )

    @mcp.tool
    async def list_tools(
        search: str | None = None, page: Page = 1, per_page: PerPage = 100
    ) -> dict[str, Any]:
        """List kitchen tools used to organise recipes (id, name, slug)."""
        return await mealie_get(
            "/api/organizers/tools",
            params={"search": search, "page": page, "perPage": per_page},
        )

    @mcp.tool
    async def list_foods(
        search: str | None = None, page: Page = 1, per_page: PerPage = 100
    ) -> dict[str, Any]:
        """List foods/ingredients defined in Mealie (id, name, plural name)."""
        return await mealie_get(
            "/api/foods",
            params={"search": search, "page": page, "perPage": per_page},
        )

    @mcp.tool
    async def list_units(
        search: str | None = None, page: Page = 1, per_page: PerPage = 100
    ) -> dict[str, Any]:
        """List measurement units defined in Mealie (id, name, abbreviation)."""
        return await mealie_get(
            "/api/units",
            params={"search": search, "page": page, "perPage": per_page},
        )

    @mcp.tool
    async def list_cookbooks(
        page: Page = 1, per_page: PerPage = 100
    ) -> dict[str, Any]:
        """List cookbooks (saved smart collections of recipes) for the household."""
        return await mealie_get(
            "/api/households/cookbooks",
            params={"page": page, "perPage": per_page},
        )

    @mcp.tool
    async def list_labels(
        search: str | None = None, page: Page = 1, per_page: PerPage = 100
    ) -> dict[str, Any]:
        """List shopping labels (id, name, color) used to group shopping-list
        items by aisle/section. Needed to set a label on a shopping item."""
        return await mealie_get(
            "/api/groups/labels",
            params={"search": search, "page": page, "perPage": per_page},
        )

    # --- Shopping lists --------------------------------------------------------

    @mcp.tool
    async def get_shopping_lists(
        page: Page = 1, per_page: PerPage = 100
    ) -> dict[str, Any]:
        """List the household's shopping lists (without their items)."""
        return await mealie_get(
            "/api/households/shopping/lists",
            params={"page": page, "perPage": per_page},
        )

    @mcp.tool
    async def get_shopping_list(
        list_id: Annotated[str, Field(description="Shopping list ID (UUID).")],
    ) -> dict[str, Any]:
        """Get a single shopping list including all of its items."""
        return await mealie_get(f"/api/households/shopping/lists/{list_id}")

    # --- Meal plans ------------------------------------------------------------

    @mcp.tool
    async def get_meal_plan(
        start_date: Annotated[
            str | None, Field(description="Start date (inclusive), format YYYY-MM-DD.")
        ] = None,
        end_date: Annotated[
            str | None, Field(description="End date (inclusive), format YYYY-MM-DD.")
        ] = None,
        page: Page = 1,
        per_page: PerPage = 100,
    ) -> dict[str, Any]:
        """Get planned meals, optionally constrained to a date range."""
        return await mealie_get(
            "/api/households/mealplans",
            params={
                "start_date": start_date,
                "end_date": end_date,
                "page": page,
                "perPage": per_page,
            },
        )

    @mcp.tool
    async def get_todays_meals() -> list[dict[str, Any]]:
        """Get the meals planned for today."""
        return await mealie_get("/api/households/mealplans/today")

    # --- Account / instance info ----------------------------------------------

    @mcp.tool
    async def get_current_user() -> dict[str, Any]:
        """Get the Mealie user the supplied token authenticates as (useful to
        confirm the token works and which household it belongs to)."""
        return await mealie_get("/api/users/self")

    @mcp.tool
    async def get_app_info() -> dict[str, Any]:
        """Get general information about the Mealie instance (version, settings)."""
        return await mealie_get("/api/app/about")

    if not include_writes:
        return

    # === Write tools (registered only when MEALIE_READONLY=false) =============
    # The per-request Mealie token's own permissions are still enforced by Mealie,
    # so a read-only token cannot mutate data even with these tools registered.

    # --- Recipes ---------------------------------------------------------------

    @mcp.tool
    async def create_recipe_from_url(
        url: Annotated[str, Field(description="Web page URL to scrape into a recipe.")],
        include_tags: bool = True,
        include_categories: bool = False,
    ) -> str:
        """Scrape a recipe from a web page URL and import it into Mealie.
        Returns the slug of the newly created recipe."""
        return await mealie_post(
            "/api/recipes/create/url",
            json={
                "url": url,
                "includeTags": include_tags,
                "includeCategories": include_categories,
            },
        )

    @mcp.tool
    async def create_recipe(
        name: Annotated[str, Field(description="Name/title of the new recipe.")],
    ) -> str:
        """Create a new (empty) recipe with the given name. Returns its slug;
        use update_recipe to fill in ingredients, instructions, etc."""
        return await mealie_post("/api/recipes", json={"name": name})

    @mcp.tool
    async def update_recipe(
        slug: Annotated[str, Field(description="Slug of the recipe to update.")],
        updates: Annotated[
            dict[str, Any],
            Field(
                description=(
                    "Fields to change (partial). Common keys: name, description, "
                    "recipeYield, recipeServings, totalTime, prepTime, performTime, "
                    "recipeIngredient (list), recipeInstructions (list of {text}), "
                    "recipeCategory (list), tags (list), rating, notes."
                )
            ),
        ],
    ) -> dict[str, Any]:
        """Partially update a recipe. Only the supplied fields are changed."""
        return await mealie_patch(f"/api/recipes/{slug}", json=updates)

    @mcp.tool
    async def delete_recipe(
        slug: Annotated[str, Field(description="Slug of the recipe to delete.")],
    ) -> dict[str, Any]:
        """Permanently delete a recipe. Returns the deleted recipe."""
        return await mealie_delete(f"/api/recipes/{slug}")

    @mcp.tool
    async def mark_recipe_made(
        slug: Annotated[str, Field(description="Slug or ID of the recipe.")],
        timestamp: Annotated[
            str | None,
            Field(description="ISO 8601 datetime; defaults to now (UTC)."),
        ] = None,
    ) -> dict[str, Any]:
        """Record that a recipe was made, updating its 'last made' date and
        adding a timeline event."""
        ts = timestamp or datetime.now(UTC).isoformat()
        # The last-made endpoint keys off the recipe UUID, not the slug, so
        # resolve via the recipe first (the GET accepts a slug or an ID).
        recipe = await mealie_get(f"/api/recipes/{slug}")
        recipe_id = recipe.get("id") if isinstance(recipe, dict) else None
        if not recipe_id:
            raise ToolError(f"Recipe '{slug}' did not return an ID; cannot mark it made.")
        return await mealie_put(
            f"/api/recipes/{recipe_id}/last-made", json={"timestamp": ts}
        )

    # --- Shopping lists --------------------------------------------------------

    @mcp.tool
    async def add_shopping_item(
        shopping_list_id: Annotated[str, Field(description="Target shopping list ID (UUID).")],
        note: Annotated[str, Field(description="Free-text item, e.g. '2 cans of beans'.")],
        quantity: Annotated[float, Field(ge=0, description="Quantity.")] = 1,
        food: Annotated[
            str | None,
            Field(description="Optional food name or ID (resolved for you)."),
        ] = None,
        unit: Annotated[
            str | None,
            Field(description="Optional unit name or ID (resolved for you)."),
        ] = None,
        label: Annotated[
            str | None,
            Field(description="Optional label name or ID (resolved for you); see list_labels."),
        ] = None,
    ) -> dict[str, Any]:
        """Add a single item to a shopping list. To add several at once, use
        add_shopping_items instead (one call rather than many)."""
        body = await _build_shopping_item(
            shopping_list_id, note, quantity, food, unit, label
        )
        return await mealie_post("/api/households/shopping/items", json=body)

    @mcp.tool
    async def add_shopping_items(
        shopping_list_id: Annotated[str, Field(description="Target shopping list ID (UUID).")],
        items: Annotated[
            list[ShoppingItemInput],
            Field(
                description=(
                    "Items to add in one call. Each has note (required) plus "
                    "optional quantity, food, unit, label."
                )
            ),
        ],
    ) -> Any:
        """Add multiple items to a shopping list in a single call. Prefer this
        over repeated add_shopping_item calls whenever adding more than one item."""
        bodies = list(
            await asyncio.gather(
                *(
                    _build_shopping_item(
                        shopping_list_id,
                        it.note,
                        it.quantity,
                        it.food,
                        it.unit,
                        it.label,
                    )
                    for it in items
                )
            )
        )
        return await mealie_post(
            "/api/households/shopping/items/create-bulk", json=bodies
        )

    @mcp.tool
    async def set_shopping_item_checked(
        item_id: Annotated[str, Field(description="Shopping list item ID (UUID).")],
        checked: Annotated[bool, Field(description="True to check off, False to uncheck.")] = True,
    ) -> dict[str, Any]:
        """Check or uncheck a shopping list item."""
        item = await mealie_get(f"/api/households/shopping/items/{item_id}")
        item["checked"] = checked
        return await mealie_put(f"/api/households/shopping/items/{item_id}", json=item)

    @mcp.tool
    async def add_recipe_to_shopping_list(
        shopping_list_id: Annotated[str, Field(description="Target shopping list ID (UUID).")],
        recipe_id: Annotated[str, Field(description="Recipe ID (UUID) to add ingredients from.")],
        scale: Annotated[
            float, Field(gt=0, description="Recipe quantity multiplier.")
        ] = 1,
    ) -> dict[str, Any]:
        """Add all of a recipe's ingredients to a shopping list."""
        return await mealie_post(
            f"/api/households/shopping/lists/{shopping_list_id}/recipe/{recipe_id}",
            json={"recipeIncrementQuantity": scale},
        )

    # --- Meal plans ------------------------------------------------------------

    @mcp.tool
    async def create_mealplan_entry(
        date: Annotated[str, Field(description="Date for the meal, format YYYY-MM-DD.")],
        entry_type: Annotated[
            MealEntryType,
            Field(description="Meal slot."),
        ] = "dinner",
        recipe_id: Annotated[
            str | None, Field(description="Recipe ID (UUID) to plan; omit for a free-text entry.")
        ] = None,
        title: Annotated[
            str | None, Field(description="Title for a free-text (no-recipe) entry.")
        ] = None,
        text: Annotated[str | None, Field(description="Optional note for the entry.")] = None,
    ) -> dict[str, Any]:
        """Add an entry to the meal plan for a given date."""
        return await mealie_post(
            "/api/households/mealplans",
            json={
                "date": date,
                "entryType": entry_type,
                "recipeId": recipe_id,
                "title": title or "",
                "text": text or "",
            },
        )

    @mcp.tool
    async def update_mealplan_entry(
        entry_id: Annotated[str, Field(description="Meal plan entry ID.")],
        date: Annotated[
            str | None,
            Field(description="New date, format YYYY-MM-DD; omit to keep current."),
        ] = None,
        entry_type: Annotated[
            MealEntryType | None,
            Field(description="New meal slot; omit to keep current."),
        ] = None,
        recipe_id: Annotated[
            str | None,
            Field(description="New recipe ID (UUID) to plan; omit to keep current."),
        ] = None,
        title: Annotated[
            str | None,
            Field(description="New title for a free-text entry; omit to keep current."),
        ] = None,
        text: Annotated[
            str | None, Field(description="New note; omit to keep current.")
        ] = None,
    ) -> dict[str, Any]:
        """Update an existing meal plan entry (change its date, meal slot, recipe,
        title or note). Only the supplied fields change; omitted fields keep their
        current value. Mealie requires the whole entry on update, so the current
        entry is fetched, the supplied fields are overwritten in place, and the
        whole object is PUT back (mirroring set_shopping_item_checked)."""
        entry = await mealie_get(f"/api/households/mealplans/{entry_id}")
        if date is not None:
            entry["date"] = date
        if entry_type is not None:
            entry["entryType"] = entry_type
        if recipe_id is not None:
            entry["recipeId"] = recipe_id
        if title is not None:
            entry["title"] = title
        if text is not None:
            entry["text"] = text
        return await mealie_put(f"/api/households/mealplans/{entry_id}", json=entry)

    @mcp.tool
    async def delete_mealplan_entry(
        entry_id: Annotated[str, Field(description="Meal plan entry ID.")],
    ) -> dict[str, Any]:
        """Delete a meal plan entry. Returns the deleted entry."""
        return await mealie_delete(f"/api/households/mealplans/{entry_id}")
