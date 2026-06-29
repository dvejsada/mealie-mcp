"""Tests for pure helper functions (no HTTP involved)."""

from __future__ import annotations

from mealie_mcp.client import _clean_params
from mealie_mcp.tools import _paginated, _summarize_recipe, _trim_recipe


def test_clean_params_drops_none_and_empty_lists():
    cleaned = _clean_params(
        {"a": 1, "b": None, "c": [], "d": ["x"], "e": False, "f": 0}
    )
    assert cleaned == {"a": 1, "d": ["x"], "e": False, "f": 0}


def test_clean_params_returns_none_when_all_dropped():
    assert _clean_params({"a": None, "b": []}) is None
    assert _clean_params(None) is None


def test_summarize_recipe_extracts_names():
    full = {
        "id": "1",
        "slug": "soup",
        "name": "Soup",
        "description": "Warm",
        "rating": 5,
        "tags": [{"name": "easy"}, {"name": "vegan"}],
        "recipeCategory": [{"name": "Dinner"}],
        "recipeInstructions": [{"text": "boil"}],  # dropped from summary
    }
    summary = _summarize_recipe(full)
    assert summary["slug"] == "soup"
    assert summary["tags"] == ["easy", "vegan"]
    assert summary["categories"] == ["Dinner"]
    assert "recipeInstructions" not in summary


def test_summarize_recipe_handles_missing_fields():
    summary = _summarize_recipe({})
    assert summary["tags"] == []
    assert summary["categories"] == []
    assert summary["name"] is None


def test_paginated_passes_through_and_overrides_items():
    data = {"items": [1, 2], "page": 1, "per_page": 50, "total": 2, "total_pages": 1}
    out = _paginated(data, items=["x"])
    assert out["items"] == ["x"]
    assert out["total"] == 2
    assert _paginated(data)["items"] == [1, 2]


def test_trim_recipe_keeps_content_and_drops_bookkeeping():
    full = {
        "id": "r1",
        "slug": "soup",
        "name": "Soup",
        "settings": {"showNutrition": True},
        "assets": [{"name": "pic"}],
        "comments": [{"text": "yum"}],
        "userId": "u1",
        "recipeIngredient": [
            {"quantity": 2, "unit": {"name": "cup"}, "food": {"name": "stock"},
             "display": "2 cups stock", "referenceId": "ref"}
        ],
        "recipeInstructions": [{"id": "i1", "text": "simmer"}],
        "tags": [{"name": "easy"}],
        "recipeCategory": [{"name": "Dinner"}],
        "tools": [{"name": "Pot"}],
    }
    trimmed = _trim_recipe(full)

    # Content preserved, reduced to readable shapes.
    assert trimmed["recipeIngredient"] == [
        {"quantity": 2, "unit": "cup", "food": "stock", "note": None,
         "display": "2 cups stock", "title": None}
    ]
    assert trimmed["recipeInstructions"] == [{"title": None, "text": "simmer"}]
    assert trimmed["tags"] == ["easy"]
    assert trimmed["categories"] == ["Dinner"]
    assert trimmed["tools"] == ["Pot"]

    # Bookkeeping dropped.
    for noise in ("settings", "assets", "comments", "userId"):
        assert noise not in trimmed


def test_trim_recipe_handles_missing_and_null_fields():
    trimmed = _trim_recipe({"recipeIngredient": [{}], "recipeInstructions": None})
    assert trimmed["recipeIngredient"] == [
        {"quantity": None, "unit": None, "food": None, "note": None,
         "display": None, "title": None}
    ]
    assert trimmed["recipeInstructions"] == []
    assert trimmed["tags"] == []
