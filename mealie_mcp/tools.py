"""Read-only MCP tools exposing a Mealie instance.

Every tool maps to a single GET endpoint of the Mealie REST API. Snake_case
arguments are translated to Mealie's camelCase query parameters. Recipe search
results are trimmed to the fields most useful to an assistant; ``get_recipe``
returns the full recipe so callers can fetch detail on demand.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from .client import mealie_get

# Reusable annotated argument types ------------------------------------------------

Page = Annotated[int, Field(ge=1, description="1-based page number.")]
PerPage = Annotated[int, Field(ge=1, le=200, description="Items per page (max 200).")]
OrderDirection = Annotated[
    Literal["asc", "desc"],
    Field(description="Sort direction for the result set."),
]


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


def register(mcp: FastMCP) -> None:
    """Register all read-only tools on the given FastMCP server."""

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
        order_by: Annotated[
            str | None,
            Field(description="Field to sort by, e.g. 'name', 'rating', 'created_at'."),
        ] = None,
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
    ) -> dict[str, Any]:
        """Get the full details of a single recipe by its slug or ID, including
        ingredients, instructions, nutrition, tags and categories."""
        return await mealie_get(f"/api/recipes/{slug}")

    @mcp.tool
    async def get_recipe_suggestions(
        foods: Annotated[
            list[str] | None,
            Field(description="Food IDs (UUIDs) you have on hand; see list_foods."),
        ] = None,
        tools: Annotated[
            list[str] | None,
            Field(description="Tool IDs (UUIDs) you have on hand; see list_tools."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="Max suggestions.")] = 10,
        max_missing_foods: Annotated[
            int, Field(ge=0, description="Allowed number of missing ingredients.")
        ] = 5,
        max_missing_tools: Annotated[
            int, Field(ge=0, description="Allowed number of missing tools.")
        ] = 5,
    ) -> dict[str, Any]:
        """Suggest recipes you can make from the foods and tools you have on hand."""
        return await mealie_get(
            "/api/recipes/suggestions",
            params={
                "foods": foods,
                "tools": tools,
                "limit": limit,
                "maxMissingFoods": max_missing_foods,
                "maxMissingTools": max_missing_tools,
            },
        )

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
