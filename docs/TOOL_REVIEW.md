# Tool review — effectiveness & scope

A review of the MCP tools in `mealie_mcp/tools.py` against two goals:

1. **Fewer tool calls per task** — let an LLM reach a meaningful result in one
   call where it currently needs two or three (mostly name→ID round-trips and
   one-item-per-call write tools), and avoid calls that fail outright.
2. **Right scope** — close gaps against the Mealie REST API where a small number
   of new tools unlock common assistant workflows.

Endpoint paths/methods below were checked against the live Mealie OpenAPI spec
(`/openapi.json` on a current instance).

> **Status:** Phases 1 and 2 of the sequencing below are **implemented** (items
> 1–7 of the TL;DR, plus the `order_by` enum and the instructions blurb). Phase 3
> (scope expansion: `set_random_mealplan`, `update_mealplan_entry`,
> `parse_ingredients`, `get_household_statistics`) is still open. See `CHANGELOG.md`.

---

## TL;DR — highest-leverage changes

| # | Change | Why it matters | Effort |
| - | --- | --- | --- |
| 1 | `get_recipe_suggestions` / `add_shopping_item` accept **food/unit/label names**, resolved server-side | Removes the mandatory `list_foods`/`list_units`/`list_labels` pre-call (3 calls → 1) | M |
| 2 | Add **`add_shopping_items`** (bulk) via `POST /shopping/items/create-bulk` | Building a list of 12 items goes from 12 calls → 1 | S |
| 3 | Fix **`mark_recipe_made`**: spec is `PUT …/last-made`, code sends `PATCH` | Tool likely 405s today → a wasted call every time | S |
| 4 | Add **`list_labels`** (`GET /api/groups/labels`) | `add_shopping_item` exposes `label_id` with no way to discover it | S |
| 5 | Make `search_recipes.order_by` a **Literal enum**, not free text | A guessed field name → 422 → retry | S |
| 6 | Add **`get_random_recipe`** (`GET /api/recipes/random`) | "What should I cook?" is one call, not search-then-pick | S |
| 7 | Trim **`get_recipe`** output (drop `settings`, `assets`, `comments`, per-ingredient UUIDs) | Full payload is token-heavy; trims roughly half the tokens with no loss of cooking content | M |

---

## Current inventory (for reference)

- **Read (always on):** `search_recipes`, `get_recipe`, `get_recipe_suggestions`,
  `list_categories`, `list_tags`, `list_tools`, `list_foods`, `list_units`,
  `list_cookbooks`, `get_shopping_lists`, `get_shopping_list`, `get_meal_plan`,
  `get_todays_meals`, `get_current_user`, `get_app_info` — **15**
- **Write (`MEALIE_READONLY=false`):** `create_recipe_from_url`, `create_recipe`,
  `update_recipe`, `delete_recipe`, `mark_recipe_made`, `add_shopping_item`,
  `set_shopping_item_checked`, `add_recipe_to_shopping_list`,
  `create_mealplan_entry`, `delete_mealplan_entry` — **10**

The overall design is good: one tool per endpoint, snake_case→camelCase
translation, search results trimmed, `set_shopping_item_checked` hides its
GET-then-PUT behind a single call. The notes below are refinements, not a rewrite.

---

## A. Reduce tool calls (the core ask)

### A1. Accept human names, not just UUIDs — the biggest win

Several tools take opaque UUIDs that the model cannot know, forcing a discovery
call first:

| Tool | Arg | Forces a pre-call to |
| --- | --- | --- |
| `get_recipe_suggestions` (tools.py:136) | `foods`, `tools` (UUIDs) | `list_foods`, `list_tools` |
| `add_shopping_item` (tools.py:362) | `food_id`, `unit_id`, `label_id` | `list_foods`, `list_units`, *(no label tool — see A4)* |

A request like *"what can I make with chicken and rice?"* currently costs three
calls: `list_foods("chicken")` → id, `list_foods("rice")` → id, then
`get_recipe_suggestions`. Resolve names → IDs **inside the tool** (look up via
`GET /api/foods?search=`, take the exact/first match, error clearly if
ambiguous) so it collapses to one call. Keep accepting raw UUIDs too.

### A2. `search_recipes` filter semantics — verify, then document precisely

`search_recipes` (tools.py:80-92) advertises *"category names or IDs"* for
`categories`/`tags`/`tools`/`foods`. Mealie's `/api/recipes` filters generally
expect **slugs (categories/tags/tools)** and **UUIDs (foods)** — plain display
names often return **zero results silently**, which reads to the model as "no
such recipe" and triggers a useless retry. Action: confirm against your target
version; if names aren't accepted, either resolve them server-side (as A1) or
fix the descriptions to say "slug or ID" so the model passes the slug it already
has from `list_categories`/`list_tags`.

### A3. Bulk shopping-item add

`add_shopping_item` adds **one** item per call (tools.py:362). Populating a
shopping list is the canonical multi-item action. Add a plural tool backed by
`POST /api/households/shopping/items/create-bulk`:

```
add_shopping_items(shopping_list_id, items: list[{note, quantity?, food?, unit?, label?}])
```

Turns "add eggs, milk, flour, sugar, butter" from 5 calls into 1. (Pairs well
with A1 name-resolution for the per-item `food`/`unit`/`label`.)

### A4. `order_by` as an enum, not free text

`search_recipes.order_by` (tools.py:96) is an open string. A model guessing
`createdAt` vs `created_at` vs `dateAdded` gets a 422 and retries. Constrain to
a `Literal["name", "rating", "created_at", "last_made", "date_added"]` (Mealie's
actual sortable fields) so the first call lands.

### A5. Trim `get_recipe` output for token efficiency

`get_recipe` (tools.py:133) returns the **entire** recipe object: `settings`,
`assets`, `comments`, `extras`, image hashes, household/group/user IDs, and a
UUID on every ingredient/instruction. That's a lot of tokens that don't help an
assistant cook. Apply a `_summarize_recipe`-style trim that **keeps** name,
description, yield/servings, times, ingredients (display text + food/unit/qty),
instructions text, notes, nutrition, tags/categories — and **drops** the
internal bookkeeping. Offer an escape hatch (`include_internal: bool = False`)
for the rare caller that needs the raw object before an `update_recipe`.

### A6. Smaller round-trip nits

- **`add_recipe_to_shopping_list`** needs a recipe **UUID** (tools.py:398).
  `search_recipes`/`get_recipe` return `id`, so this is usually fine — but
  document that it's the UUID `id`, not the slug, since every *other* recipe
  tool keys off slug. A mismatch here is a silent 404.
- **`per_page`** caps at 200 (tools.py:30). Mealie accepts `perPage=-1` for
  "all" — worth allowing for the small reference lists (categories/units) so the
  model never has to paginate them.

---

## B. Correctness fixes (a broken tool is a wasted call)

| Tool | Issue | Fix |
| --- | --- | --- |
| `mark_recipe_made` (tools.py:357) | Sends `PATCH /api/recipes/{slug}/last-made`; current spec exposes **`PUT …/{recipe_id}/last-made`** only | Switch to `PUT`; confirm whether the path segment accepts slug or requires the UUID `id` |
| `add_shopping_item` (tools.py:368) | Exposes `label_id` but there is **no tool to list labels** | Add `list_labels` (B/§C) so the value is discoverable |
| `set_shopping_item_checked` (tools.py:391) | GET-then-PUT echoes the whole item back; fine, but a concurrent edit is clobbered | Acceptable; note it's last-write-wins |

---

## C. Scope expansion (new tools), prioritized

All paths verified against the Mealie OpenAPI spec.

### High value — common assistant workflows, low cost

| Tool | Endpoint | Use case |
| --- | --- | --- |
| `get_random_recipe` | `GET /api/recipes/random` | "Surprise me / what should I cook tonight" in one call |
| `list_labels` | `GET /api/groups/labels` | Needed to make `add_shopping_item.label_id` usable (see B) |
| `add_shopping_items` *(write)* | `POST /api/households/shopping/items/create-bulk` | Bulk add (A3) |
| `set_random_mealplan` *(write)* | `POST /api/households/mealplans/random` | "Plan a random dinner for Friday" |
| `update_mealplan_entry` *(write)* | `PUT /api/households/mealplans/{id}` | Move/relabel a planned meal without delete+recreate |
| `parse_ingredients` | `POST /api/parser/ingredients` | Turn free-text ("2 cups flour") into structured food/unit/qty — high-fidelity recipe creation/shopping |

### Medium value

| Tool | Endpoint | Use case |
| --- | --- | --- |
| `get_household_statistics` | `GET /api/households/statistics` | "How many recipes/tags do I have?" totals in one call |
| `duplicate_recipe` *(write)* | `POST /api/recipes/{id}/duplicate` | "Make a copy I can tweak" |
| `get_recipe_timeline` | `GET /api/recipes/{id}/timeline` | When was this last made / made-history |
| `add_recipe_comment` *(write)* | `POST /api/recipes/{id}/comments` | Save a note/tweak against a recipe |
| `get_cookbook` | `GET /api/households/cookbooks/{id}` | Inspect a cookbook's filter rules (list only enumerates them today) |
| `export_recipe` | `GET /api/recipes/exports` | Hand a recipe back in a portable format |

### Low value / skip for now

- Mealplan **rules** (`/mealplans/rules`), **webhooks**, **image/asset upload**
  (`/recipes/{id}/image`, `/assets`) — admin/config surface, rarely useful to a
  chat assistant and mostly binary-payload or scheduling concerns.
- Recipe **bulk actions** (`/recipes/bulk/actions`) — powerful but a footgun for
  an LLM (mass tag/delete); leave behind the UI.

---

## D. Description / ergonomics polish

- **`update_recipe.updates`** (tools.py:325) is a free `dict` — flexible but the
  model must already know Mealie's exact camelCase schema (`recipeInstructions`
  as `[{text}]`, ingredient shape, etc.). The docstring lists common keys, which
  is good; consider linking the shape to what `get_recipe` returns so a
  read-modify-write loop is reliable. Worst-case malformed bodies surface as 422s
  (the client already maps these to a clear `ToolError`).
- **Server `INSTRUCTIONS`** (server.py:28) still says *"Read-only access"* even
  when writes are enabled. Make the blurb reflect the actual mode so the model
  knows write tools exist.
- **`get_meal_plan`** returns the raw envelope; meal-plan entries embed the full
  recipe. Consider trimming the embedded recipe to a summary (as `search_recipes`
  does) to keep a week's plan from blowing the context window.

---

## Suggested sequencing

1. **Ship now (correctness + tiny):** fix `mark_recipe_made` (B), add
   `list_labels` + `get_random_recipe`, enum-ify `order_by` (A4), correct the
   `INSTRUCTIONS` blurb (D).
2. **Next (call-count wins):** name→ID resolution (A1), `add_shopping_items`
   bulk (A3), `get_recipe` trim (A5).
3. **Then (scope):** `set_random_mealplan`, `update_mealplan_entry`,
   `parse_ingredients`, `get_household_statistics`.

Each new write tool stays gated behind `MEALIE_READONLY=false` and inherits the
per-request Mealie token's own permissions, so the security model is unchanged.
