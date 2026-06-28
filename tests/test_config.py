"""Tests for environment-driven configuration."""

from __future__ import annotations

import pytest

from mealie_mcp.config import Settings, _env_bool, _split_tokens


def test_split_tokens_handles_blanks_and_spacing():
    assert _split_tokens("a, b ,,c ") == ["a", "b", "c"]
    assert _split_tokens("") == []
    assert _split_tokens(None) == []


@pytest.mark.parametrize(
    "raw,expected",
    [("true", True), ("1", True), ("YES", True), ("on", True),
     ("false", False), ("0", False), ("nope", False)],
)
def test_env_bool(monkeypatch, raw, expected):
    monkeypatch.setenv("SOME_FLAG", raw)
    assert _env_bool("SOME_FLAG", default=True) is expected


def test_env_bool_default_when_unset(monkeypatch):
    monkeypatch.delenv("SOME_FLAG", raising=False)
    assert _env_bool("SOME_FLAG", default=True) is True


def test_from_env_requires_auth_token(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN"):
        Settings.from_env()


def test_from_env_parses_values(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "tok1, tok2")
    monkeypatch.setenv("MEALIE_BASE_URL", "https://mealie.example.com/")
    monkeypatch.setenv("MEALIE_READONLY", "false")
    monkeypatch.setenv("MCP_PORT", "9000")
    settings = Settings.from_env()
    assert settings.auth_tokens == ["tok1", "tok2"]
    assert settings.mealie_base_url == "https://mealie.example.com"  # trailing slash stripped
    assert settings.read_only is False
    assert settings.port == 9000


def test_from_env_defaults_to_read_only(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "tok")
    monkeypatch.delenv("MEALIE_READONLY", raising=False)
    assert Settings.from_env().read_only is True
