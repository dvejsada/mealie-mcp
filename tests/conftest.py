"""Shared test fixtures.

The server reads the per-request Mealie token from the active HTTP request via
``get_http_request()``. In tests there is no real HTTP request, so we monkeypatch
that dependency to return a fake request carrying whatever headers a test needs,
and use ``respx`` to mock Mealie's HTTP responses.
"""

from __future__ import annotations

import httpx
import pytest

from mealie_mcp import client as mclient
from mealie_mcp.config import Settings

BASE_URL = "https://mealie.test"


class FakeRequest:
    """Minimal stand-in for a Starlette Request exposing case-folded headers."""

    def __init__(self, headers: dict[str, str]):
        # Real Starlette headers are case-insensitive and lower-cased; our code
        # looks up lower-case header names, so a plain lower-cased dict suffices.
        self.headers = {k.lower(): v for k, v in headers.items()}


@pytest.fixture
def settings() -> Settings:
    return Settings(auth_tokens=["mcp-token"], mealie_base_url=BASE_URL)


@pytest.fixture
async def configured(monkeypatch, settings):
    """Install a shared httpx client and a default (authenticated) request.

    Yields a mutable dict whose ``headers`` entry can be reassigned by a test to
    simulate missing/alternate headers.
    """
    http = httpx.AsyncClient()
    mclient.configure(http, settings)

    state = {"headers": {"x-mealie-token": "mealie-token"}}
    monkeypatch.setattr(mclient, "get_http_request", lambda: FakeRequest(state["headers"]))

    yield state

    mclient.shutdown()
    await http.aclose()
