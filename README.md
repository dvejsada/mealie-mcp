# mealie-mcp

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server for
[Mealie](https://mealie.io), built with [FastMCP](https://gofastmcp.com) and served
over the **Streamable HTTP** transport. Ships as a Docker container.

It exposes **tools only** — no MCP resources or prompts.

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

All tools are read-only.

**Recipes** — `search_recipes`, `get_recipe`, `get_recipe_suggestions`
**Reference data** — `list_categories`, `list_tags`, `list_tools`, `list_foods`, `list_units`, `list_cookbooks`
**Household** — `get_shopping_lists`, `get_shopping_list`, `get_meal_plan`, `get_todays_meals`
**Instance** — `get_current_user`, `get_app_info`

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

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `MCP_AUTH_TOKEN` | **yes** | — | Comma-separated secret bearer token(s) for the MCP endpoint. |
| `MEALIE_BASE_URL` | no¹ | — | Default Mealie base URL (e.g. `https://mealie.example.com`). |
| `MEALIE_TIMEOUT` | no | `30` | Outbound request timeout in seconds. |
| `MEALIE_VERIFY_SSL` | no | `true` | Set `false` for self-signed Mealie certs. |
| `MCP_HOST` | no | `0.0.0.0` | Bind address. |
| `MCP_PORT` | no | `8000` | Bind port. |
| `MCP_PATH` | no | `/mcp` | Endpoint path. |
| `MCP_LOG_LEVEL` | no | `info` | uvicorn log level. |

¹ Required unless every client sends the `X-Mealie-Url` header.

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

Two GitHub Actions workflows are included (`.github/workflows/`):

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
