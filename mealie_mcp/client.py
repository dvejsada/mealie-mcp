"""Per-request HTTP access to the Mealie REST API.

The MCP endpoint itself is gated by a static bearer token (see ``server.py``),
but the *Mealie* credential is supplied per request: each MCP client sends its
own Mealie API token in the ``X-Mealie-Token`` header. That token is read from
the active HTTP request and forwarded to Mealie as a bearer token, so a single
server instance can serve many Mealie users.

A single shared ``httpx.AsyncClient`` is used for connection pooling; it carries
no credentials of its own — auth headers are attached on every call.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from starlette.datastructures import Headers

from .config import MEALIE_TOKEN_HEADER, MEALIE_URL_HEADER, Settings

# Shared client, owned by the server lifespan (see server.py).
_http_client: httpx.AsyncClient | None = None
_settings: Settings | None = None


def configure(client: httpx.AsyncClient, settings: Settings) -> None:
    """Install the shared HTTP client and settings (called from the lifespan)."""
    global _http_client, _settings
    _http_client = client
    _settings = settings


def shutdown() -> None:
    global _http_client
    _http_client = None


def _require_client() -> httpx.AsyncClient:
    if _http_client is None:
        raise ToolError("HTTP client is not initialised (server starting up?).")
    return _http_client


def _request_headers() -> Headers:
    """Return the raw headers of the active HTTP request.

    Credentials are read straight off the Starlette request via
    ``get_http_request()`` — deliberately *not* via FastMCP's
    ``get_http_headers()`` helper. ``get_http_headers()`` strips a fixed set of
    "problematic" headers (``authorization`` among them) before returning, so
    routing credential lookups through it would silently drop the per-request
    Mealie token carried in ``X-Mealie-Token`` as well as the endpoint's own
    ``Authorization`` gate. Reading the request object directly keeps every
    header intact.
    """
    try:
        request = get_http_request()
    except Exception:  # pragma: no cover - only happens outside an HTTP context
        raise ToolError(
            "No active HTTP request; this server requires HTTP transport."
        ) from None
    return request.headers


def _resolve_request() -> tuple[str, str]:
    """Return ``(base_url, mealie_token)`` for the current request.

    Raises ToolError with an actionable message if either is missing.
    """
    headers = _request_headers()

    token = (headers.get(MEALIE_TOKEN_HEADER) or "").strip()
    if not token:
        raise ToolError(
            f"Missing Mealie credential: send your Mealie API token in the "
            f"'{MEALIE_TOKEN_HEADER}' header."
        )

    base_url = (headers.get(MEALIE_URL_HEADER) or "").strip()
    if base_url:
        base_url = base_url.rstrip("/")
    elif _settings and _settings.mealie_base_url:
        base_url = _settings.mealie_base_url
    else:
        raise ToolError(
            f"No Mealie base URL configured. Set the MEALIE_BASE_URL environment "
            f"variable, or send the target instance URL in the '{MEALIE_URL_HEADER}' header."
        )

    return base_url, token


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop ``None`` values and empty lists so they are not sent as query args."""
    if not params:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)) and len(value) == 0:
            continue
        cleaned[key] = value
    return cleaned or None


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except Exception:
        text = response.text.strip()
        return text[:300] if text else "<no body>"
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("message") or body)
    return str(body)


async def mealie_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any = None,
) -> Any:
    """Perform an authenticated request against the Mealie API and return JSON.

    ``path`` must start with ``/`` (e.g. ``/api/recipes``). Errors are converted
    into ToolError so the MCP client receives a clear, structured message.
    """
    client = _require_client()
    base_url, token = _resolve_request()
    url = f"{base_url}{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    try:
        response = await client.request(
            method, url, params=_clean_params(params), json=json, headers=headers
        )
    except httpx.RequestError as exc:
        raise ToolError(f"Could not reach Mealie at {url}: {exc}") from exc

    if response.status_code == 401:
        raise ToolError(
            "Mealie rejected the API token (401 Unauthorized). Check the "
            f"'{MEALIE_TOKEN_HEADER}' header value."
        )
    if response.status_code == 403:
        raise ToolError("Mealie denied access to this resource (403 Forbidden).")
    if response.status_code == 404:
        raise ToolError(f"Mealie resource not found (404): {path}")
    if response.status_code == 422:
        raise ToolError(f"Mealie rejected the request (422): {_error_detail(response)}")
    if response.is_error:
        raise ToolError(
            f"Mealie API error {response.status_code} for {path}: {_error_detail(response)}"
        )

    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise ToolError(f"Mealie returned a non-JSON response for {path}.") from exc


async def mealie_get(path: str, params: dict[str, Any] | None = None) -> Any:
    return await mealie_request("GET", path, params=params)


async def mealie_post(path: str, json: Any = None, params: dict[str, Any] | None = None) -> Any:
    return await mealie_request("POST", path, json=json, params=params)


async def mealie_put(path: str, json: Any = None) -> Any:
    return await mealie_request("PUT", path, json=json)


async def mealie_patch(path: str, json: Any = None) -> Any:
    return await mealie_request("PATCH", path, json=json)


async def mealie_delete(path: str) -> Any:
    return await mealie_request("DELETE", path)
