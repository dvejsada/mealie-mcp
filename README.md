# mealie-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server for
[Mealie](https://mealie.io), built with [FastMCP](https://gofastmcp.com) and served
over the **Streamable HTTP** transport. Ships as a Docker container.

It exposes **tools only** — no MCP resources or prompts. It is **read-only by
default**; write tools can be enabled with `MEALIE_READONLY=false`.

## How auth works

There are two independent credentials:

| Credential | Header | Purpose |
| --- | --- | --- |
| **MCP endpoint token** | `Authorization: Bearer <token>` | A static secret (set via `MCP_AUTH_TOKEN`) that gates the server. Requests without a valid token are rejected with `401`. |
| **Mealie API token** | `X-Mealie-Token: <token>` | Supplied **per request** by each client. The server forwards it to Mealie as a bearer token, so one server can serve many Mealie users. |

Optionally, a client can target a different Mealie instance per request with the
`X-Mealie-Url: https://other-mealie.example.com` header (otherwise `MEALIE_BASE_URL`
is used).

Get a Mealie API token from your Mealie profile: **Profile → Manage API Tokens**.

## Tools

### Read tools (always available)

**Recipes** — `search_recipes`, `get_recipe`, `get_recipe_suggestions`
**Reference data** — `list_categories`, `list_tags`, `list_tools`, `list_foods`, `list_units`, `list_cookbooks`
**Household** — `get_shopping_lists`, `get_shopping_list`, `get_meal_plan`, `get_todays_meals`
**Instance** — `get_current_user`, `get_app_info`

### Write tools (only when `MEALIE_READONLY=false`)

**Recipes** — `create_recipe_from_url`, `create_recipe`, `update_recipe`, `delete_recipe`, `mark_recipe_made`
**Shopping** — `add_shopping_item`, `set_shopping_item_checked`, `add_recipe_to_shopping_list`
**Meal plans** — `create_mealplan_entry`, `delete_mealplan_entry`

> Write tools respect the per-request Mealie token's own permissions, so a
> read-only Mealie token can never mutate data even when write tools are enabled.

## Run with Docker

```bash
cp .env.example .env
# edit .env: set MCP_AUTH_TOKEN (a long random secret) and MEALIE_BASE_URL
docker compose up --build -d
```

The MCP endpoint is then available at `http://<host>:8000/mcp`, with an
unauthenticated liveness probe at `http://<host>:8000/healthz`.

> The endpoint token is the only thing standing between the internet and your
> Mealie instance. Put the server behind a reverse proxy with TLS, or on a
> private network, and use a long random `MCP_AUTH_TOKEN`.

## Run locally (without Docker)

```bash
pip install -r requirements.txt
export MCP_AUTH_TOKEN="a-long-random-secret"
export MEALIE_BASE_URL="https://mealie.example.com"
python main.py
```

## Connecting a client

Point your MCP client at the Streamable HTTP endpoint and send both headers.
Example with the FastMCP client:

```python
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

transport = StreamableHttpTransport(
    url="http://localhost:8000/mcp",
    headers={
        "Authorization": "Bearer <your MCP_AUTH_TOKEN>",
        "X-Mealie-Token": "<your Mealie API token>",
    },
)

async with Client(transport) as client:
    tools = await client.list_tools()
    result = await client.call_tool("search_recipes", {"search": "soup"})
```

### LibreChat

See [`examples/librechat.yaml`](examples/librechat.yaml) for a ready-to-use
`mcpServers` entry. It maps the endpoint bearer token to a LibreChat environment
variable and each user's Mealie token to a per-user `customUserVars` field, so
every LibreChat user acts as their own Mealie account.

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `MCP_AUTH_TOKEN` | **yes** | — | Comma-separated secret bearer token(s) for the MCP endpoint. |
| `MEALIE_BASE_URL` | no¹ | — | Default Mealie base URL (e.g. `https://mealie.example.com`). |
| `MEALIE_READONLY` | no | `true` | Set `false` to also register write tools. |
| `MEALIE_TIMEOUT` | no | `30` | Outbound request timeout in seconds. |
| `MEALIE_VERIFY_SSL` | no | `true` | Set `false` for self-signed Mealie certs. |
| `MCP_HOST` | no | `0.0.0.0` | Bind address. |
| `MCP_PORT` | no | `8000` | Bind port. |
| `MCP_PATH` | no | `/mcp` | Endpoint path. |
| `MCP_LOG_LEVEL` | no | `info` | uvicorn log level. |
| `MCP_AUTH_DEBUG` | no | `false` | Log a masked diagnostic for each request hitting the auth gate (to troubleshoot `401`s). See [Troubleshooting](#troubleshooting-401-unauthorized). |

¹ Required unless every client sends the `X-Mealie-Url` header.

## Troubleshooting `401 Unauthorized`

A `401` means the **endpoint token** (the `Authorization: Bearer <token>` gate,
*not* your Mealie token) was missing or didn't match `MCP_AUTH_TOKEN`. Many MCP
clients react to a `401` by probing for OAuth (`GET /.well-known/oauth-*`, which
this server returns `404` for, since it uses static tokens, not OAuth) — those
`404`s are a symptom of the `401`, not a separate problem.

To see exactly what the gate receives, set `MCP_AUTH_DEBUG=true` and reconnect.
Each request to the gate is logged with a **masked** summary (the token itself
is never logged — only its length and a SHA-256 fingerprint):

```
auth-debug enabled: accepting 1 token(s) with fingerprints ['0c45a1f1']
auth-debug: POST /mcp authorization=scheme=Bearer token_len=10 fp=0c45a1f1 matches_configured=True -> 200
auth-debug: POST /mcp authorization=scheme=Bearer token_len=5 fp=02b60b3b matches_configured=False -> 401
auth-debug: POST /mcp authorization=absent (no Authorization header reached the server) -> 401
auth-debug: POST /mcp authorization=scheme=Bearer <empty token> -> 401
```

Read it as:

- **`matches_configured=False`** — the client sent a token, but it doesn't equal
  any `MCP_AUTH_TOKEN` value. Check for typos, quoting, or trailing whitespace.
- **`absent`** — no `Authorization` header reached the server. The client isn't
  sending it, or a reverse proxy/ingress stripped it before it arrived.
- **`<empty token>`** — the client sent `Authorization: Bearer ` with no value,
  typically an unset `${...}` variable in the client config.
- **`matches_configured=True -> 200`** — the gate is fine; the problem is
  elsewhere.

## Docker Hub images

Released versions are published to Docker Hub at
[`georgx22/mealie-mcp`](https://hub.docker.com/r/georgx22/mealie-mcp)
(multi-arch: `linux/amd64`, `linux/arm64`):

```bash
docker run -d -p 8000:8000 \
  -e MCP_AUTH_TOKEN="a-long-random-secret" \
  -e MEALIE_BASE_URL="https://mealie.example.com" \
  georgx22/mealie-mcp:latest
```

## CI/CD

Three GitHub Actions workflows are included (`.github/workflows/`):

- **`ci.yml`** — runs `ruff`, `pyright`, and `pytest` on every push/PR (Python 3.11–3.13).
- **`docker-publish.yml`** — builds and pushes the multi-arch image to Docker Hub
  when a GitHub Release is published (tags `X.Y.Z`, `X.Y`, `X`, and `latest`).
- **`claude.yml`** — runs [Claude Code](https://github.com/anthropics/claude-code-action)
  when someone mentions `@claude` in an issue, PR, or review comment.

Configure these repository secrets (**Settings → Secrets and variables → Actions**):

| Secret | Used by | How to get it |
| --- | --- | --- |
| `DOCKERHUB_USERNAME` | docker-publish | Your Docker Hub username (with push access to `georgx22/mealie-mcp`). |
| `DOCKERHUB_TOKEN` | docker-publish | A Docker Hub **access token** (Account Settings → Security → New Access Token). |
| `CLAUDE_CODE_OAUTH_TOKEN` | claude | Run `claude setup-token` locally (Claude Pro/Max), paste the token. |

To cut a release (which triggers the image build):

```bash
gh release create v0.1.0 --generate-notes
```

## Development

```bash
pip install -e ".[dev]"
ruff check .     # lint
pyright          # type check
pytest -q        # tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for details. Changes are tracked in
[CHANGELOG.md](CHANGELOG.md). Licensed under [MIT](LICENSE).
