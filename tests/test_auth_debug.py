"""Tests for the opt-in auth-gate diagnostic (MCP_AUTH_DEBUG).

These cover the masking logic that lets an operator tell a token *mismatch*
apart from a *stripped/absent* header when chasing a 401 — without ever logging
the token itself.
"""

from __future__ import annotations

import logging

from mealie_mcp.server import (
    _AuthDebugMiddleware,
    _configure_debug_logging,
    _describe_authorization,
    _token_fingerprint,
)
from mealie_mcp.server import logger as auth_logger


def _scope(headers: dict[str, str]) -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
    }


def test_fingerprint_is_stable_short_and_distinct():
    fp = _token_fingerprint("super-secret")
    assert fp == _token_fingerprint("super-secret")
    assert len(fp) == 8
    assert _token_fingerprint("other") != fp


def test_describe_absent_header():
    assert "absent" in _describe_authorization(_scope({}), set())


def test_describe_empty_token():
    desc = _describe_authorization(_scope({"authorization": "Bearer "}), set())
    assert "empty token" in desc


def test_describe_distinguishes_match_from_mismatch_without_leaking():
    fp = _token_fingerprint("good-token")
    match = _describe_authorization(_scope({"authorization": "Bearer good-token"}), {fp})
    mismatch = _describe_authorization(_scope({"authorization": "Bearer wrong"}), {fp})

    assert "matches_configured=True" in match
    assert f"fp={fp}" in match
    assert "token_len=10" in match  # len("good-token")

    assert "matches_configured=False" in mismatch
    # The raw secret is never placed in the log line — only length + fingerprint.
    assert "good-token" not in match


async def test_middleware_forwards_response_and_logs_status(caplog):
    sent: list[dict] = []

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 401, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    middleware = _AuthDebugMiddleware(inner, token_fingerprints=set())
    with caplog.at_level(logging.INFO, logger="mealie_mcp.auth"):
        await middleware(_scope({}), receive, send)

    # The wrapped response is passed through untouched...
    assert any(
        m["type"] == "http.response.start" and m["status"] == 401 for m in sent
    )
    # ...and the gate decision is logged with the (absent) credential + status.
    line = next(r.getMessage() for r in caplog.records if "auth-debug" in r.getMessage())
    assert "absent" in line
    assert "-> 401" in line


async def test_middleware_passes_through_non_http_scopes():
    seen: list[str] = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        pass

    middleware = _AuthDebugMiddleware(inner, token_fingerprints=set())
    await middleware({"type": "lifespan"}, receive, send)
    assert seen == ["lifespan"]


def test_configure_debug_logging_is_idempotent():
    # Save and restore global logger state so this never leaks into other tests.
    saved_handlers = list(auth_logger.handlers)
    saved_level = auth_logger.level
    saved_propagate = auth_logger.propagate
    auth_logger.handlers.clear()
    try:
        _configure_debug_logging()
        _configure_debug_logging()  # second call must not add a second handler
        assert auth_logger.level == logging.INFO
        assert len(auth_logger.handlers) == 1
        assert auth_logger.propagate is False
    finally:
        auth_logger.handlers[:] = saved_handlers
        auth_logger.setLevel(saved_level)
        auth_logger.propagate = saved_propagate
