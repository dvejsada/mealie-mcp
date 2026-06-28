# Contributing

Thanks for your interest in improving **mealie-mcp**!

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Checks

All three must pass before a change is merged (CI runs them on every push/PR):

```bash
ruff check .     # lint + import sorting
pyright          # type checking
pytest -q        # tests
```

`ruff check --fix .` auto-fixes most lint issues.

## Running the server locally

```bash
export MCP_AUTH_TOKEN="a-long-random-secret"
export MEALIE_BASE_URL="https://mealie.example.com"
# export MEALIE_READONLY=false   # to enable write tools
python main.py
```

## Adding a tool

Tools live in `mealie_mcp/tools.py`. Read tools are registered unconditionally;
write tools go inside the `if not include_writes: return` guard. Each tool should:

- map to a single Mealie REST endpoint via the `mealie_*` helpers in `client.py`,
- use `Annotated[..., Field(description=...)]` for non-obvious arguments,
- have a concise docstring (it becomes the tool description),
- be covered by a test in `tests/` (mock Mealie with `respx`).

## Guidelines

- Keep tools focused and well-described — the descriptions are what an LLM reads.
- Don't log or echo Mealie tokens.
- Update `CHANGELOG.md` under `[Unreleased]`.
