# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Read per-request credentials directly off the HTTP request instead of routing
  through FastMCP's `get_http_headers()`, which strips the `authorization`
  header (and could strip the `X-Mealie-Token` credential). Whitespace-only
  Mealie tokens are now treated as missing. Added an end-to-end HTTP test that
  exercises the real auth gate and asserts the Mealie token is forwarded to
  Mealie rather than dropped.

### Added
- Write tools (registered only when `MEALIE_READONLY=false`): `create_recipe_from_url`,
  `create_recipe`, `update_recipe`, `delete_recipe`, `mark_recipe_made`,
  `add_shopping_item`, `set_shopping_item_checked`, `add_recipe_to_shopping_list`,
  `create_mealplan_entry`, `delete_mealplan_entry`.
- `MEALIE_READONLY` configuration flag (defaults to `true`).
- `examples/librechat.yaml` — example LibreChat `mcpServers` configuration.
- Test suite (pytest + respx), `ruff` and `pyright` configuration, and a CI workflow.
- `LICENSE` (MIT), `CONTRIBUTING.md`, Dependabot configuration.

## [0.1.0] - 2026-06-28

### Added
- Initial read-only MCP server for Mealie built on FastMCP, served over the
  Streamable HTTP transport and packaged as a Docker container.
- 15 read-only tools covering recipes, organizers/reference data, shopping lists,
  meal plans, and instance/account info.
- Static bearer token gate on the MCP endpoint; per-request Mealie API token via
  the `X-Mealie-Token` header (with optional `X-Mealie-Url` override).
- Unauthenticated `/healthz` liveness probe.
- GitHub Actions workflows for publishing the Docker image on release and for
  `@claude` mention handling.
