# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `get_random_recipe` read tool (`GET /api/recipes/random`) — a single random
  recipe for "what should I cook?" prompts.
- `list_labels` read tool (`GET /api/groups/labels`) — discover shopping labels,
  which `add_shopping_item`/`add_shopping_items` accept by name or ID.
- `add_shopping_items` write tool (`POST …/shopping/items/create-bulk`) — add
  several shopping-list items in one call instead of one tool call per item.
- `get_recipe` now accepts `include_internal` (default `false`): the trimmed view
  drops `settings`, `assets`, `comments`, owning IDs and per-ingredient UUIDs;
  pass `true` for the raw Mealie object.

### Changed
- `get_recipe_suggestions` (`foods`/`tools`) and `add_shopping_item`
  (`food`/`unit`/`label`, renamed from `*_id`) now accept a plain **name or a
  UUID** — names are resolved server-side, removing the mandatory `list_*`
  pre-call.
- `search_recipes.order_by` is now a constrained enum
  (`name`/`rating`/`created_at`/`updated_at`/`last_made`) instead of free text,
  so a mistyped field can no longer cause a `422`.
- Server `instructions` now reflect the actual read/write mode instead of always
  claiming "read-only".

### Fixed
- `mark_recipe_made` now sends `PUT …/{recipe_id}/last-made` against the recipe's
  UUID (resolved from the slug), matching the current Mealie API. It previously
  sent `PATCH …/{slug}/last-made`, which the current API does not expose.

## [0.2.0] - 2026-06-28

### Fixed
- Read per-request credentials directly off the HTTP request instead of routing
  through FastMCP's `get_http_headers()`, which strips the `authorization`
  header (and could strip the `X-Mealie-Token` credential). Whitespace-only
  `X-Mealie-Token` / `X-Mealie-Url` values are now treated as absent. Added an
  end-to-end HTTP test that exercises the real auth gate and asserts the Mealie
  token is forwarded to Mealie rather than dropped.

### Added
- `examples/librechat.yaml` now sets `requiresOAuth: false` (required): LibreChat's
  OAuth auto-detection otherwise probes this static-token server without the
  configured headers, gets a `401`, and misclassifies it as OAuth-protected so the
  static Bearer token is never sent. Documented in the README troubleshooting section.
- `MCP_AUTH_DEBUG` flag: when enabled, logs a masked diagnostic for every request
  reaching the auth gate (Authorization present/absent, scheme, token length and a
  SHA-256 fingerprint vs. the configured tokens) to troubleshoot `401`s without
  ever logging the token. Includes a "Troubleshooting `401`" section in the README.
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
