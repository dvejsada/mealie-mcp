"""Environment-driven configuration for the Mealie MCP server.

All configuration comes from environment variables so the server can be run
unchanged inside a Docker container. The only required value is at least one
static bearer token used to gate the MCP HTTP endpoint.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split_tokens(raw: str | None) -> list[str]:
    """Parse a comma-separated list of bearer tokens, ignoring blanks."""
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Header carrying the per-request Mealie API token. Each MCP client supplies its
# own Mealie token here so a single server can serve multiple Mealie users.
MEALIE_TOKEN_HEADER = "x-mealie-token"

# Optional per-request override for the Mealie base URL (multi-instance setups).
MEALIE_URL_HEADER = "x-mealie-url"


@dataclass(frozen=True)
class Settings:
    """Resolved server settings."""

    # Static bearer token(s) accepted on the MCP endpoint's Authorization header.
    auth_tokens: list[str] = field(default_factory=list)

    # Default Mealie base URL (e.g. https://mealie.example.com). May be overridden
    # per request via the X-Mealie-Url header. Required if the header is not sent.
    mealie_base_url: str | None = None

    # HTTP server bind settings (inside the container).
    host: str = "0.0.0.0"
    port: int = 8000
    path: str = "/mcp"

    # Outbound HTTP behaviour when talking to Mealie.
    request_timeout: float = 30.0
    verify_ssl: bool = True

    # When True (default) only read tools are registered. Set MEALIE_READONLY=false
    # to also expose write tools (create/update/delete). Note that the per-request
    # Mealie token's own permissions still apply, so a read-only Mealie token can
    # never mutate data regardless of this flag.
    read_only: bool = True

    log_level: str = "info"

    @classmethod
    def from_env(cls) -> Settings:
        tokens = _split_tokens(os.getenv("MCP_AUTH_TOKEN"))
        if not tokens:
            raise RuntimeError(
                "MCP_AUTH_TOKEN is required: set it to one or more comma-separated "
                "secret bearer tokens that MCP clients must present in the "
                "'Authorization: Bearer <token>' header."
            )

        base_url = os.getenv("MEALIE_BASE_URL")
        if base_url:
            base_url = base_url.rstrip("/")

        return cls(
            auth_tokens=tokens,
            mealie_base_url=base_url,
            host=os.getenv("MCP_HOST", "0.0.0.0"),
            port=int(os.getenv("MCP_PORT", "8000")),
            path=os.getenv("MCP_PATH", "/mcp"),
            request_timeout=float(os.getenv("MEALIE_TIMEOUT", "30")),
            verify_ssl=_env_bool("MEALIE_VERIFY_SSL", True),
            read_only=_env_bool("MEALIE_READONLY", True),
            log_level=os.getenv("MCP_LOG_LEVEL", "info"),
        )
