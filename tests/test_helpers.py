"""Tests for pure helper functions (no HTTP involved)."""

from __future__ import annotations

from mealie_mcp.client import _clean_params
from mealie_mcp.tools import _paginated, _summarize_recipe


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
