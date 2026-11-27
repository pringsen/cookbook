# Cookbook: self-hosted family cookbook for TrueNAS / Docker

This README is two things at once:

1. The documentation for the app (install, configure, use).
2. A **complete specification** you can hand to an AI coding assistant (or a developer) to rebuild the
   application from scratch with the same behaviour, data model and deployment. Sections marked **Spec**
   are written for that purpose. To rebuild, use a prompt like:

   > Build the application described in this README exactly as specified. Follow every **Spec** section
   > (tech stack, data model, routes, business rules, AI integration, Docker/TrueNAS deployment). Keep the
   > file layout. When done, run the acceptance tests in section 13 against the Docker Compose stack.

Version described: **1.4** (November 2026): book-like design, tablet mode, e-paper mode, cook mode, kitchen display,
bread recipes with a baker's percentage calculator, sourdough levain calculator, e-paper whole-recipe view sized to the display.

---

## 1. What it is

A self-hosted web app for a household's recipes, running as two Docker containers (web app + PostgreSQL),
designed for **TrueNAS SCALE** ("Install via YAML" custom app) but usable on any Docker host. It is used
from desktop and phone browsers on the home network.

### Features

| Feature | What the user can do |
|---|---|
| Recipes | Write, edit, delete recipes with photo, description, servings, prep/cook time, ingredients (with sections), steps, notes, tags, source link, 1–5 star rating, favourite flag. Search, filter by tag/favourite, sort A–Z / newest / best rated. Scale ingredient quantities to any number of servings. Print view. |
| Photo import (AI) | Upload one or more photos (cookbook page, handwritten card, screenshot). Claude (Anthropic API) transcribes them into a recipe draft, which the user reviews in the normal edit form before saving. Optionally keeps the first photo as recipe picture. |
| URL import | Paste a recipe URL. The page's schema.org/Recipe data is parsed (recipe-scrapers, then own JSON-LD parser). If the page has no structured data and AI is configured, Claude reads the page text. Recipe image is downloaded. Result opens as a draft in the edit form. |
| Manual entry | "Write a recipe" form. |
| Bread recipes | A recipe can be of type **Bread**. Instead of an ingredient list it stores a baker's percentage formula (same layout as a bakery spreadsheet): flour blend (each flour as % of total flour), other ingredients as % of flour (water, salt, oil…, liquids marked), levain as % of flour and its composition. Dough size = number of pieces × piece weight, or a target dough weight. The recipe page shows a table with **Recipe / Levain / Final dough** columns (% and grams), total hydration, and lets you resize (e.g. 28 × 75 g) without editing; the table updates live while you type. Live preview while editing. Shopping list and cook mode use the computed grams. |
| Levain calculator | For sourdough: build the levain from a starter with a feed ratio starter : water : flour (e.g. 1:3:5) and a **starter hydration** input (e.g. 60 % stiff or 100 % liquid). Shows grams of starter, water and flour, the resulting levain hydration and its total flour/water. Inside a bread recipe it is a switch: the levain's water % then follows from the ratio, and the build amount can include an extra % (leftover in the jar). Stand-alone page at `/levain`; results update live while you type (no Calculate button). |
| Cookbooks | User-defined collections (name, description, colour). A recipe can be in several cookbooks. Add/remove recipes from either side. |
| Cooking calendar | Log what was cooked, on which date, **for whom** (free text, comma separated), notes and rating. Month grid view, list of the month, filter by person. Each recipe page shows how often and when it was cooked, with history. Entries can be for a recipe or free text ("Leftover stir fry"). |
| Meal planner | Week view (Mon–Sun) with meals breakfast / lunch / dinner / snack. Add a recipe (with optional servings) or a note ("Eating out") to any day. Mark a planned meal as cooked (creates a calendar entry). Navigate weeks. |
| Shopping list | Add ingredients from a recipe (choose which, scaled to servings), or all ingredients of a planned week in one click, or type items. Identical items are merged and quantities summed, with g/kg and ml/l/dl/cl unified. Tick items off (no page reload), remove checked, clear all, plain-text export. Shared by the whole household. |
| Accounts | First visitor creates the admin account. Admin adds/removes people. Everyone can change their own password. All data is shared by the household. |
| Tablet mode (iPad) | Per-device display mode with large touch targets, bigger text, ingredients pinned next to the steps, planner cards that fit portrait iPads. **Cook mode** shows one step at a time in large type with the ingredients alongside; swipe, arrow keys or big Back/Next buttons; the screen stays on (Wake Lock). |
| E-paper mode | Per-device mode for e-ink readers and displays (Kindle, Kobo, PocketBook, Boox, reMarkable): pure black on white, no colours, shadows, photos in lists, animations or hover effects; thick borders; large serif/sans type. Cook mode shows the **whole recipe on one screen** (ingredients, levain build, method, notes) as one text flow in columns: the bigger the display, the more columns and the larger the type (Kindle portrait: 1 column, 10" panel: 2–3, 13" landscape: 3–4). "One step at a time" switches to the paged mode (plain links, works without JavaScript). On screens ≥ 1100 px wide the recipe page's method also flows into columns. |
| Kitchen display | Read-only `/kitchen` page for a wall tablet or e-paper screen: today's and the next days' meals, the shopping list, recently cooked dishes and, where the screen has room, today's recipe in full ("Cooking today"). On e-paper it shows as many days as fit (3 / 5 / 7 by screen size); auto-refresh every 15 min. Opened with a secret display link (no login) that an admin creates or revokes in Settings. |
| Settings | Anthropic API key and model (admin only; env vars override), people, password, JSON export. |
| Backup | `/export.json` download of all recipes, cookbooks and calendar entries; dataset snapshots on TrueNAS. |

---

## 2. Spec: tech stack

| Layer | Choice (pinned versions used in v1.0) |
|---|---|
| Language | Python 3.13 (`python:3.13-slim` base image) |
| Web framework | FastAPI 0.165 + Starlette 1.10, served by Uvicorn 0.54 (`uvicorn[standard]`) |
| Templates | Jinja2 3.1, **server-rendered HTML**, no SPA, no build step. Small vanilla JS file for enhancements; every feature must also work without JS. |
| ORM / DB | SQLAlchemy 2.1 (typed `Mapped[]` models), PostgreSQL 17 (`postgres:17-alpine`) via `psycopg[binary]` 3.3. SQLite fallback when `DATABASE_URL` is unset (dev). Tables created with `Base.metadata.create_all()` at start-up (no migrations in v1). |
| Sessions | Starlette `SessionMiddleware` (signed cookie, needs `itsdangerous`), cookie `cookbook_session`, 60 days, SameSite=Lax, Secure if `SECURE_COOKIES=true`. |
| Forms / uploads | `python-multipart` |
| HTTP client | `httpx` 0.29 |
| Images | Pillow 13 |
| URL import | `recipe-scrapers` 15.14 |
| AI | `anthropic` Python SDK 2.14, model `claude-opus-5-5` by default |
| Validation | pydantic 2.14 (FastAPI dependency) |

`requirements.txt`:

```
fastapi==0.165.0
uvicorn[standard]==0.54.0
SQLAlchemy==2.1.9
psycopg[binary]==3.3.9
Jinja2==3.1.6
python-multipart==0.0.34
itsdangerous==2.2.0
httpx==0.29.0
anthropic==2.14.0
pillow==13.0.0
recipe-scrapers==15.14.0
pydantic==2.14.4
```

---

## 3. Spec: file layout

```
cookbook/
├── README.md                  # this file
├── TRUENAS.md                 # step-by-step TrueNAS install guide (section 11)
├── Dockerfile
├── docker/entrypoint.sh
├── docker-compose.yml         # generic Docker host
├── truenas-app.yaml           # paste into TrueNAS "Install via YAML" (pulls ghcr.io/pringsen/cookbook)
├── truenas-app-local.yaml     # same, for an image built on the NAS (cookbook:local)
├── .env.example
├── .dockerignore              # .git, data, *.pyc, __pycache__, .env
├── requirements.txt
├── .github/workflows/docker-publish.yml   # build & push to ghcr.io on every push to main
└── app/
    ├── __init__.py
    ├── config.py              # env vars, data dirs, secret key
    ├── db.py                  # engine, models, settings helpers
    ├── auth.py                # scrypt password hashing
    ├── ingredients.py         # ingredient-line parser, scaling, unit merging
    ├── importer.py            # URL fetch + schema.org parsing
    ├── ai.py                  # Claude photo/text → recipe
    ├── bread.py               # baker's percentages + levain build (section 6.7)
    ├── main.py                # FastAPI app, all routes, helpers
    ├── static/  style.css, app.js, icon.svg,
    │            fonts/ (Newsreader + Inter woff2, OFL licences)
    └── templates/
        base.html, _card.html, setup.html, login.html, home.html,
        recipes.html, recipe.html, recipe_form.html, import.html,
        cookbooks.html, cookbook.html, calendar.html, planner.html,
        shopping.html, settings.html, error.html,
        cook.html (step-by-step cook mode), kitchen.html (kitchen display),
        _bread_editor.html (bread form part), _bread_table.html (recipe/levain/final table),
        _bread_lists.html (levain + final dough lists for cook mode), _levain_build.html, levain.html
```

---

## 4. Spec: configuration (`app/config.py`)

| Env var | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `/data` | Persistent folder. Contains `uploads/` (recipe photos) and `.secret_key`. |
| `DATABASE_URL` | `sqlite:///$DATA_DIR/cookbook.db` | e.g. `postgresql+psycopg://cookbook:PASS@db:5432/cookbook` |
| `ANTHROPIC_API_KEY` | empty | If set, overrides the key saved in Settings. |
| `AI_MODEL` | empty → `claude-opus-5-5` | If set, overrides the model saved in Settings. |
| `SECRET_KEY` | generated | If unset, a random `secrets.token_urlsafe(48)` is created once in `$DATA_DIR/.secret_key` (chmod 600) and reused. |
| `SECURE_COOKIES` | `false` | `true` behind HTTPS. |
| `TZ` | `UTC` | Container time zone; "today" uses local date. |
| `PUID` / `PGID` | `568` / `568` | User the app process runs as (TrueNAS `apps` user). Used by the entrypoint. |

On start-up: create `DATA_DIR` and `DATA_DIR/uploads`; call `init_db()` with up to 30 retries, 2 s apart
(the DB container may still be starting); exit with a clear message if it never connects.

---

## 5. Spec: data model (`app/db.py`)

SQLAlchemy 2 declarative models. For SQLite, enable `PRAGMA foreign_keys=ON` on connect.

**users**: `id` PK · `username` str(80) unique, indexed, stored lower-case · `display_name` str(120) default "" ·
`password_hash` str(255) · `is_admin` bool · `created_at` datetime server default now.
Property `name` = display_name or username.

**settings**: `key` str(80) PK · `value` text. Keys used: `anthropic_api_key`, `ai_model`, `kiosk_token`
(secret for the kitchen display link; empty = turned off).
Helpers `get_setting(db, key, default)` and `set_setting(db, key, value)`.

**recipes**: `id` · `title` str(300) indexed · `description` text · `servings` int null · `prep_minutes` int null ·
`cook_minutes` int null · `ingredients` text (one ingredient per line; a line ending in `:` or starting with `#`
is a section header) · `instructions` text (one step per line; header rule same as ingredients) · `notes` text ·
`tags` str(500) (comma separated) · `source_url` str(1000) · `image` str(300) (file name in uploads) ·
`rating` int null (1–5) · `favorite` bool · `kind` str(20) `standard|bread` (default standard) · `bread` text (JSON
bread spec, see 6.7; empty for standard recipes) · `created_by_id` FK users ON DELETE SET NULL · `created_at` ·
`updated_at` (onupdate now).
Relationships: `cookbooks` (many-to-many), `logs` (CookLog, ordered by cooked_on desc).
Properties: `tag_list`, `total_minutes` (prep+cook, None if both None), `steps` (non-empty instruction lines).

**Migration**: `create_all()` does not add columns to existing tables. `init_db()` therefore checks a
`NEW_COLUMNS` map (`recipes.kind VARCHAR(20) NOT NULL DEFAULT 'standard'`, `recipes.bread TEXT NOT NULL DEFAULT ''`)
with `inspect()` and runs `ALTER TABLE … ADD COLUMN` for each missing one, so a v1.2 database upgrades in place.

**cookbooks**: `id` · `name` str(200) · `description` text · `color` str(20) default `#c2410c` · `created_at`.
Relationship `recipes` ordered by title.

**recipe_cookbook** (association): `recipe_id` FK CASCADE, `cookbook_id` FK CASCADE, composite PK.

**cook_logs** (cooking calendar): `id` · `recipe_id` FK recipes ON DELETE SET NULL, nullable · `title` str(300)
(used when no recipe, and filled with the recipe title when a recipe is deleted) · `cooked_on` date indexed ·
`guests` str(500) ("for whom", comma separated names) · `notes` text · `rating` int null · `user_id` FK users
SET NULL · `created_at`. Property `label` = recipe title or title or "Untitled".

**meal_plan**: `id` · `day` date indexed · `meal` str(20) one of `breakfast|lunch|dinner|snack` (default dinner) ·
`recipe_id` FK recipes ON DELETE CASCADE, nullable · `note` str(300) · `servings` int null · `cooked` bool.
Property `label` = recipe title or note.

**shopping_items**: `id` · `name` str(300) · `quantity` float null · `unit` str(40) (canonical unit, see 6) ·
`note` str(300) (e.g. recipe names the item came from) · `checked` bool · `position` int · `created_at`.

---

## 6. Spec: business rules

### 6.1 Ingredient parsing (`app/ingredients.py`)

`parse(line) -> Parsed(quantity: float|None, unit: str, name: str, note: str)`

1. Clean: replace unicode fractions (½ ⅓ ⅔ ¼ ¾ ⅕… ⅛ ⅜ ⅝ ⅞) with `a/b`; `1½` → `1 1/2`; strip leading bullets `- * • ·`.
2. Quantity at the start: integer, decimal with `.` or `,`, fraction `1/2`, mixed `1 1/2`, or a range
   `2-3`, `2–3`, `2 to 3`, `2 bis 3` (for shopping, the **upper** bound is used).
3. Unit directly after the quantity (glued `200g` or spaced, optional trailing `.`, optional `of`), looked up
   case-insensitively in an alias table and mapped to a canonical unit:
   - metric: g, kg, mg, ml, cl, dl, l (gram/grams/gramm, liter/litre…)
   - US: tsp (teaspoon, t), tbsp (tablespoon, tbs, tbl), cup (cups, c), oz, lb (lbs, pound), pint, quart, fl oz
   - German: EL/Essl/Esslöffel → tbsp, TL/Teel/Teelöffel → tsp, Msp/Prise/Prisen → pinch,
     Pck/Päckchen/Packung/Pack → pkg, Stk/Stück/St → pc, Dose/Dosen → can, Bund → bunch,
     Zehe/Zehen → clove, Becher/Tasse/Tassen → cup, Scheibe/Scheiben → slice
   - also: pc/pcs/piece, can, bunch, clove, pinch, dash, slice
   Unknown words are part of the name, not a unit.
4. Text after the first comma becomes `note`; text in parentheses is moved to `note`.
5. `normalize_name()` for merging: lower-case, collapse spaces, simple plural folding
   (`-oes/-ches/-shes/-xes` → drop `es`; trailing `s` dropped unless `ss`; only for names > 3 chars).
6. `fmt_qty()`: integers without decimals; otherwise nearest of halves, thirds, quarters, eighths shown as
   `1 1/2`, `3/4`; else up to 2 decimals.

### 6.2 Scaling

Recipe page has `?servings=N`. If the recipe has `servings`, factor = N / servings. `scale_line()` multiplies
the leading quantity (and both ends of a range) and keeps the rest of the line as written (e.g. `2 EL Olivenöl`
→ `4 EL Olivenöl`). Header lines are untouched. Show "Quantities scaled from X to N servings".

### 6.3 Shopping list merging

`add_to_shopping(db, line, factor=1, note="")`:
- Skip header lines. Parse; multiply quantity by factor.
- Convert to base unit: kg→g ×1000, mg→g ×0.001, l→ml ×1000, dl→ml ×100, cl→ml ×10.
- Find an **unchecked** item with same `normalize_name`, same unit and same "has quantity" state. If found:
  add the quantity, append the note (recipe title) if not already present. Else insert at the end
  (`position = max+1`).
- Display: g ≥ 1000 → kg, ml ≥ 1000 → l (`display_amount()`), e.g. 900 ml + 2 l → **2.9 l milk**.
- From a recipe: checkboxes for each ingredient (all pre-checked), uses current servings.
- From the planner: all ingredients of all planned recipes in the shown week, each scaled by the entry's
  servings ÷ recipe servings. Flash "Added ingredients from N planned meals … duplicates merged".
- Manual add: textarea, one item per line (Enter submits when single-line).

### 6.4 Planner → calendar

"✓ cooked" on a planned entry sets `cooked=True` and creates a CookLog for that day (recipe or note as
title). Recipe page "Plan this" adds a MealPlan entry and redirects to that week.

### 6.5 Calendar

Month grid (weeks start Monday) using `calendar.Calendar(0).monthdatescalendar`. Days outside the month are
dimmed; today is outlined. A "Cooked for" tag bar lists every distinct name ever entered in `guests`
(split on commas); clicking filters the month by `guests ILIKE %name%`. The log form has a datalist of these
names. On phones (< 640 px) entries collapse into small coloured bars.

### 6.6 Recipe deletion

Deletes the image file; copies the title into its CookLogs (so the calendar keeps the name); meal-plan entries
cascade; cookbook links cascade.

### 6.7 Bread: baker's percentages and levain (`app/bread.py`)

Spec stored as JSON in `recipes.bread`:
```json
{"flours": [{"name": "Bread flour", "pct": 90, "levain_pct": 100}, {"name": "Whole wheat flour", "pct": 10, "levain_pct": 0}],
 "others": [{"name": "Water", "pct": 70, "levain_pct": 100, "liquid": true}, {"name": "Salt", "pct": 2, "levain_pct": 0, "liquid": false}],
 "levain_pct": 20, "pieces": 2, "piece_weight": 900, "total_weight": null, "piece_name": "loaves",
 "levain_build": {"enabled": false, "starter": 1, "water": 3, "flour": 5, "starter_hydration": 100, "extra_pct": 10}}
```
Number inputs accept `,` as decimal separator and ignore `%`/`g`. Missing keys fall back to the defaults above.
Rows without a name are dropped. If `liquid` is missing, a row counts as liquid when its name contains water/wasser/
milk/milch/beer/bier/juice/saft.

Calculation (`compute(spec, pieces, piece_weight, total_weight)`; URL overrides win over the saved values):
- Total dough T = override total, else saved `total_weight`, else pieces × piece weight. Piece weight shown = T / pieces.
- Total % P = 100 + sum of `others[].pct`. Total flour F = T × 100 / P.
- Each flour: weight = F × pct / 100. Each other row: weight = F × pct / 100.
- Levain weight L = F × levain_pct / 100. Levain flour LF = L × 100 / (100 + sum of `others[].levain_pct`).
  Levain amount of a row = LF × row.levain_pct / 100 (flour rows' levain_pct are shares of the levain flour).
- Final dough = recipe − levain for every row. Hydration = sum of liquid `pct`; levain hydration = sum of liquid `levain_pct`.
- Warnings (shown above the table, never blocking): flours ≠ 100 %, levain flours ≠ 100 % (when levain > 0), any
  final-dough amount < 0 ("The levain needs more X than the whole recipe has"), build enabled but no liquid row.
- Grams are shown with one decimal (`153.5 g`; whole numbers without decimals).
- On save the standard `ingredients` text is filled with the total amounts (`614 g Flour …`, one line per row with
  weight > 0) and `servings` = pieces, so search, shopping list and scaling keep working.

Levain build (`levain_build(target, starter, water, flour, starter_hydration)`):
- parts = s + w + f; unit = target / parts; starter = s × unit, water = w × unit, flour = f × unit.
- Starter flour = starter × 100 / (100 + starter hydration); starter water = starter − starter flour.
- Levain hydration = (water + starter water) / (flour + starter flour) × 100.
- In a bread recipe with the build enabled: the first liquid row's levain % is set to that hydration and other liquid
  rows to 0 (the levain flour split is still taken from the flour rows). Build target = L × (1 + extra_pct / 100).

Worked example (Philipp's "Bread rolls" sheet): 14 × 75 g = 1050 g, water 65 % + salt 3 % + oil 3 % = 171 % → flour 614.0 g;
levain 50 % = 307.0 g at 100 % → 153.5 g flour + 153.5 g water; final dough = recipe − levain.
Levain example: 45 g at 1:3:5 → 5 g starter, 15 g water, 25 g flour; with a 100 % starter the levain holds
27.5 g flour + 17.5 g water = 63.6 % hydration; with a 60 % starter 60 % (28.1 g flour, 16.9 g water).

The JS module `Bread` in `app.js` repeats these formulas for the live preview in the editor and on `/levain`;
the server result is authoritative.

Live updates (all pages still work without JavaScript, e.g. on e-readers): buttons marked `data-js-hide`
(Calculate, Recalculate, Scale) are hidden when JS runs. `/levain` recalculates in the browser on every input and
keeps the URL in sync (`history.replaceState`). On the recipe page the scaler forms (`data-live-form`; servings for
standard recipes, pieces × piece weight for bread) re-fetch the page 250 ms after typing stops and swap the
`data-live-swap` parts (meta line, Start cooking link, bread table + shopping form, ingredient list). Cook mode
accepts `piece_weight` / `total` too, so a resized dough carries into it.

---

## 7. Spec: AI integration (`app/ai.py`)

- Key and model: env var wins, else Settings table, else model `claude-opus-5-5`.
- Client: `anthropic.Anthropic(api_key=..., timeout=180, max_retries=2)`. Calls run in a thread pool
  (`run_in_threadpool`) so the server stays responsive.
- Request: `client.beta.messages.create(model, max_tokens=16000, system=SYSTEM, messages=[user content],
  output_config={"format": {"type": "json_schema", "schema": RECIPE_SCHEMA}},
  betas=["server-side-fallback-2026-07-01"], fallbacks="default")`. If that returns a 400 mentioning
  "fallback", retry the same request with `client.messages.create(**params)` without betas/fallbacks.
  No `thinking` or sampling parameters.
- `RECIPE_SCHEMA` (all required, `additionalProperties: false`): `found` bool, `title` str, `description` str,
  `servings` int|null, `prep_minutes` int|null, `cook_minutes` int|null, `ingredients` str[],
  `instructions` str[], `notes` str, `tags` str[].
- System prompt (verbatim):
  > You transcribe recipes for a personal cookbook app. Copy the recipe faithfully in its original language;
  > do not translate, invent, or embellish. Rules:
  > - ingredients: one entry per ingredient, formatted 'quantity unit name, preparation' (e.g. '200 g flour',
  >   '2 eggs, beaten'). If the recipe groups ingredients, add the group name as its own entry ending with a
  >   colon (e.g. 'For the sauce:').
  > - instructions: one entry per step, without leading step numbers.
  > - servings / times: numbers only, null if not stated. Times in minutes.
  > - notes: tips, variations, or storage hints that appear in the source; otherwise empty.
  > - tags: up to 5 short tags (cuisine, course, main ingredient), in the recipe's language.
  > - If several photos are given they are pages of the same recipe, in order.
  > - If you cannot find a recipe, set found to false and leave other fields empty.
- Photos: max 6, total ≤ 60 MB. Each is EXIF-rotated, converted to RGB, downscaled to ≤ 1568 px long edge,
  JPEG q88, sent as base64 `image` blocks. With several photos, a text block "Photo i:" precedes each.
  Final text block: "Transcribe the recipe in this photo." / "…in these photos." plus optional
  "Note from the user: …".
- Page text (URL fallback): visible text of the page (scripts/styles/nav/header/footer removed, max 60 000 chars)
  wrapped in `<page>…</page>` with "Extract the recipe from this web page text (source: URL)."
- Response handling: `stop_reason == "refusal"` → "The AI declined…"; `max_tokens` → "too long"; parse the
  text blocks as JSON; `found == false` → "No recipe could be found". Map SDK errors to friendly messages:
  AuthenticationError (key rejected), NotFoundError (model not found), RateLimitError, other APIStatusError,
  APIConnectionError (no internet). All shown as a red flash on the import page.

---

## 8. Spec: URL import (`app/importer.py`)

1. Require `http(s)://`. GET with a browser-like User-Agent, `Accept-Language: en,de;q=0.8`, follow redirects,
   20 s timeout.
2. `recipe_scrapers.scrape_html(html, org_url=url, supported_only=False)`; read title, description, yields,
   prep/cook/total time, ingredient groups (group purpose becomes a `Purpose:` header line), ingredients,
   instructions_list, category + keywords as tags (max 12), image. Each getter wrapped in try/except.
3. If that fails or yields no title + (ingredients or steps): own JSON-LD parser. Scan all
   `<script type="application/ld+json">`, find a node with `@type` Recipe (also inside `@graph`, `mainEntity`,
   `itemListElement`, lists). ISO-8601 durations (`PT1H30M`) → minutes. `recipeInstructions` may be a string,
   HowToStep list, or HowToSection (section name becomes a header line). HTML entities and tags stripped.
4. If still nothing and the user ticked "Let AI read the page" and a key exists → AI page-text extraction.
5. Download the image (≤ 15 MB) and store it like an upload. Render the edit form pre-filled with the draft,
   an info note, and hidden `image_existing` so the photo is attached on save.

---

## 9. Spec: routes (`app/main.py`)

All pages except `/setup`, `/login`, `/healthz`, `/static`, `/media` require login; unauthenticated
requests redirect to `/setup` if there are no users yet, else to `/login?next=<path>`. Every POST form
carries a hidden `csrf` field (or `x-csrf-token` header for fetch) checked against the session token;
mismatch → 400 "Your session expired…". After POST: 303 redirect (PRG) with a flash message stored in the
session. Errors render `error.html` with code and friendly text.

| Method & path | Purpose |
|---|---|
| GET `/healthz` | `{"ok": true}` (Docker healthcheck) |
| GET/POST `/setup` | create first user (admin); only while no users exist; password ≥ 8 chars |
| GET/POST `/login`, POST `/logout` | sign in/out; `next` must be a local path |
| GET `/` | home: counts (recipes, cookbooks, unchecked shopping items), next 7 days of plan, 8 newest recipes, 6 latest calendar entries |
| GET `/recipes` | list; query `q` (ILIKE on title/tags/ingredients/description), `tag`, `fav`, `kind=bread`, `sort` = title/new/rating; tag bar with "Breads" |
| GET/POST `/recipes/new` | manual form (`?cookbook=ID` preselects, `?kind=bread` opens the bread editor) |
| GET `/recipes/{id}` | detail; `?servings=N` scaling; for bread `?servings=<pieces>&piece_weight=G` or `?total=G` resizes the dough |
| GET `/levain?target=45&s=1&w=3&f=5&h=100` | stand-alone levain calculator (works without JS, live with JS) |
| GET/POST `/recipes/{id}/edit` | edit; image upload / remove / keep |
| POST `/recipes/{id}/delete`, `/favorite`, `/cookbooks`, `/shopping`, `/cooked`, `/plan` | actions from the detail page |
| GET `/import?tab=photo|url` | import page |
| POST `/import/url`, `/import/photo` | return the pre-filled recipe form (not saved yet) |
| GET `/cookbooks`, POST `/cookbooks/new` | list + create |
| GET `/cookbooks/{id}`; POST `…/edit`, `…/add`, `…/remove/{rid}`, `…/delete` | cookbook page and actions |
| GET `/calendar?month=YYYY-MM&guest=Name`; POST `/calendar/new`, `/calendar/{id}/delete` | cooking calendar |
| GET `/planner?week=YYYY-MM-DD`; POST `/planner/add`, `/{id}/delete`, `/{id}/move`, `/{id}/cooked`, `/planner/shopping` | meal planner |
| GET `/shopping`, `/shopping.txt`; POST `/shopping/add`, `/{id}/toggle` (JSON if `x-requested-with: fetch`), `/{id}/delete`, `/shopping/clear` (`what=all` clears everything, else checked only) | shopping list |
| GET `/settings`; POST `/settings/ai` (admin), `/settings/password`, `/settings/users/new` (admin), `/settings/users/{id}/delete` (admin, not self) | settings |
| GET `/export.json` | download JSON backup |
| GET `/display/{standard|tablet|epaper}?next=/path` | set the per-device display mode cookie, redirect back |
| GET `/recipes/{id}/cook?step=N&servings=S` (bread also `&piece_weight=G` or `&total=G`) | cook mode (step 0 = ingredients, 1..n = steps; out-of-range steps are clamped) |
| GET `/kitchen?token=T&display=tablet|epaper&refresh=900&days=3` | kitchen display; allowed when signed in or with a valid token; invalid token → 403; no token and not signed in → login |
| POST `/settings/kiosk` (admin) | create a new display link token (`action=revoke` turns it off) |
| `/static/*`, `/media/*` | static files and uploaded images (`DATA_DIR/uploads`) |

Uploaded/imported images: EXIF-rotated, RGB, max 1600 px, saved as `<uuid4hex>.jpg` (JPEG q85). Never accept
`/` or `..` in stored file names.

Passwords: `hashlib.scrypt` (n=2^14, r=8, p=1, 16-byte salt, dklen 32), stored as `scrypt$<salt hex>$<hash hex>`,
compared with `hmac.compare_digest`.

---

## 10. Spec: UI and design

**Design brief: modern, simple, beautiful and minimalistic, almost like a book.** The app should feel like a
well-set printed cookbook rather than a dashboard: warm paper, ink-black serif text, hairline rules instead of
boxes and shadows, small-caps labels, generous white space, one restrained accent colour.

**Typography** (fonts are bundled in `app/static/fonts/`, no external requests, SIL OFL licences included):
- Reading text and headings: **Newsreader** (variable, optical sizes, upright + italic), body 18 px,
  line-height 1.6, old-style numerals (`font-feature-settings: "onum"`). Headings weight 500, slight negative
  tracking; page titles `clamp(2rem, 4.2vw, 3rem)`, recipe titles up to 3.6 rem.
- Controls and labels: **Inter** (variable) at small sizes. Labels, nav, meta and section kickers are
  UPPERCASE, letter-spacing .09–.1 em, ~.72–.8 rem ("small caps" look).
- Descriptions and notes in italic serif. Brand "Cookbook" in italic serif next to a small icon.

**Colour tokens** (CSS custom properties on `:root`, dark variant via `prefers-color-scheme`):
paper `--bg #f7f3ec`, leaf `--surface #fcfaf6`, `--surface2 #efe8dc`, ink `--text #1f1a16`,
`--muted #7a6e62`, hairline `--line #e0d6c7`, accent deep terracotta `--accent #9a3412`
(dark: bg `#171411`, text `#ece4d8`, accent `#e08a5f`). `--radius 6px`, no shadows.

**Components:**
- Top bar = running head: paper background, 1 px bottom rule, nav centred as uppercase text links, active item
  underlined in the accent colour; "+ Add recipe" as an outlined button; ⚙ settings icon.
- Buttons: rectangular (6 px radius), transparent with hairline border; primary = solid ink, turns accent on hover.
- Section heads: serif heading + small uppercase link on the right, 1 px rule underneath.
- Home: greeting, three numbers in a ruled row (serif figures, small-caps captions), ruled lists for
  the next 7 days and recently cooked, recipe grid.
- Recipe cards: portrait 4:5 photo "plate" (or italic initial on tinted paper), serif title caption, small meta
  line; no card box; title underlines on hover. Grid `minmax(230px,1fr)`, 2 columns on phones.
- Recipe page = cookbook page: full-width 16:9 photo, then centred: cookbook name as kicker, large serif title,
  italic description, meta row between two rules with vertical separators, tags, actions (Start cooking,
  Edit, Favourite, Print). Below: two columns (ingredients 1fr / method 2fr; one column under 760 px), each
  opened by a 2 px ink rule and an uppercase heading; ingredients ruled with hairlines and italic section
  headers; steps numbered with large accent serif numerals; notes as italic text with an accent left rule.
  Secondary actions (I cooked this, Plan this, Cookbooks, History, Delete) are a ruled accordion with +/–.
- Cookbooks: book-like tiles with a coloured spine, title set at the bottom. Cookbook page: centred title with a
  short colour bar above.
- Calendar and planner: ruled ledger grids (shared 1 px lines, no gaps); today marked by a 2 px accent line on
  top and a lighter leaf background; entries are plain text with an accent left rule (calendar) or dotted rules
  (planner).
- Shopping list: ruled notepad (2 px ink rule on top, hairlines between items), round tick buttons that fill
  with ink when checked, amounts in small bold sans.
- Forms: hairline inputs on the lighter leaf colour, serif textareas for recipe text, dashed photo drop zone.
- Flash messages: text with a 2 px coloured left rule, no box.
- Print stylesheet hides navigation and panels.
- `app.js`: print button, busy spinner, photo previews, list filter, auto-growing textarea, fetch-based
  shopping toggle (falls back to normal submit), cook-mode swipe/keys/wake lock. No dialogs/alerts.

The CSS is one file: base styles, then component styles, then mode layers (`.mode-tablet`, `.mode-epaper`),
then the "book design layer", then e-paper/tablet overrides that must win over it.

### 10.1 Display modes (tablet and e-paper)

- Mode is **per device**, stored in cookie `cookbook_display` (`standard` | `tablet` | `epaper`, 5 years,
  SameSite=Lax), set via `/display/{mode}`. A `?display=` query parameter overrides it for one request (used by
  the kitchen display link). Unknown values fall back to `standard`. `render()` passes `mode` to every template;
  `base.html` puts `class="mode-{{ mode }}"` on `<body>`. All mode styling is CSS scoped under
  `.mode-tablet` / `.mode-epaper`; templates differ only where noted.
- Switching: a small footer on every signed-in page ("Display: Standard · Tablet · E-paper") and a card picker
  in Settings → "Display mode for this device".
- **Tablet:** base font 18 px; buttons ≥ 48 px high, inputs larger, checkboxes 1.6 rem; nav items larger;
  shopping ticks 2.4 rem; at ≥ 900 px width the recipe ingredients card is `position: sticky` next to the
  steps; planner wraps to 260 px cards below 1100 px; cook-mode buttons ≥ 64 px. `apple-mobile-web-app-capable`
  meta so it can be added to the iPad home screen.
- **E-paper:** override the colour tokens on `body.mode-epaper` to pure black/white (wins over dark mode);
  font 20 px; remove all `box-shadow`, transitions, animations and backdrop filters; underline links;
  non-sticky top bar with a 3 px black rule; active nav and primary buttons are solid black with white text;
  2 px black borders on cards, panels, calendar days, planner days, inputs, tags; recipe photos hidden
  (list thumbnails and the recipe hero) because photos ghost on e-ink; today outlined 4 px; no spinner;
  dimmed states use dotted borders instead of opacity. Theme colour meta becomes white.

### 10.2 Cook mode (`cook.html`)

Full-screen page without the top bar/footer (`hide_nav`). Top: "✕ Close" (back to recipe), title,
"Ingredients" or "Step n of m". Step 0 lists the (scaled) ingredients in two columns with headers. Steps 1..m
show the step text very large (`clamp(1.4rem, 3.2vw, 2.4rem)`) with a round step number and the section name
if the step follows an instruction header line. In tablet mode the ingredient list is shown beside the step.
Bottom bar: "‹ Ingredients/Back", progress dots, "Start/Next ›", and on the last step "Done ✓" linking to
`/recipes/{id}#cooked` (opens the "I cooked this" panel). Navigation is plain links (works on e-readers);
`app.js` adds swipe (> 60 px horizontal), arrow/space/PageUp/PageDown keys and `navigator.wakeLock.request("screen")`
(re-requested on visibility change, silently ignored if unsupported). "Start cooking" button on the recipe page
passes the chosen servings. In the kitchen display, signed-in users get links straight into cook mode.

Two views, `?view=page|steps` (default: `page` in e-paper mode, `steps` otherwise; a "Whole recipe" / "One step at
a time" button in the top bar switches, keeping the size parameters; in e-paper mode the step links carry
`&view=steps`). **Page view** (`.cook.cookwide`, no max width): one `.cookpage` element with CSS multi-column
layout `columns: 16em; column-gap: 2.2em`, font size `clamp(1.05rem, .5rem + .8vw + .35vh, 1.6rem)`, so the
number of columns and the type size follow the screen. Content in order: Ingredients (bread: levain and final
dough lists), "Build the levain" (bread with a levain build: starter/water/flour grams and ratio), Method
(numbered, instruction headers kept), Notes. Headings avoid column breaks after them; list items never split.
Bottom bar: "‹ Recipe" and "Done ✓".

### 10.3 Kitchen display (`kitchen.html`)

No top bar. Header: weekday and date, "Updated HH:MM". Two columns (one on narrow screens): "Meals" for today,
tomorrow and the following day(s) (`days`, 1–7, default 3) with meal labels and struck-through cooked entries,
and "Shopping list (n)" as two-column ☐ checklist with amounts, then the last 3 calendar entries (6 on e-paper).
Days sit in a `.kdays` grid (`repeat(auto-fill, minmax(15rem, 1fr))`). E-paper: `days` defaults to 7 and CSS hides
what doesn't fit (≤ 700 px wide or tall: 3 days; 701–1199 px wide: 5; wider: 7), the page uses the full width
(meals 2fr, lists 1fr). Below, "Cooking today: <recipe>" shows the first uncooked recipe planned for today
(dinner preferred), scaled to the planned servings (bread: computed totals), ingredients and numbered method
in `columns: 16em`; hidden on screens ≤ 700 px wide or tall. `<meta
http-equiv="refresh">` every `refresh` seconds (default 900, minimum 60, 0 = off). Settings shows ready-made
tablet and e-paper links, "Open", "New link" (rotates the token) and "Turn off".

---

## 11. Spec: Docker and TrueNAS deployment

### Dockerfile

```dockerfile
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/data PUID=568 PGID=568
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)" || exit 1
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
```

### docker/entrypoint.sh

Starts as root, creates `$DATA_DIR/uploads`, chowns `$DATA_DIR`, `uploads` and anything up to depth 2 not owned
by `PUID` to `PUID:PGID`, then `exec setpriv --reuid=$PUID --regid=$PGID --clear-groups "$@"`. If not root,
just `exec "$@"`.

### docker-compose.yml (generic host)

Project name `cookbook`. Service `db`: `postgres:17-alpine`, env `POSTGRES_DB=cookbook`, `POSTGRES_USER=cookbook`,
`POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?…}`, volume `./data/postgres:/var/lib/postgresql/data`, healthcheck
`pg_isready -U cookbook -d cookbook` every 10 s. Service `app`: `build: .`, `image: cookbook:local`,
`depends_on: db: condition: service_healthy`, env `DATABASE_URL=postgresql+psycopg://cookbook:${POSTGRES_PASSWORD}@db:5432/cookbook`,
`ANTHROPIC_API_KEY`, `AI_MODEL`, `TZ`, `SECURE_COOKIES` from `.env`, volume `./data/app:/data`, port
`${COOKBOOK_PORT:-8080}:8000`. Both `restart: unless-stopped`.

`.env.example`: `POSTGRES_PASSWORD` (letters and digits only, e.g. `openssl rand -hex 24`), `COOKBOOK_PORT=8080`,
`ANTHROPIC_API_KEY=`, `AI_MODEL=`, `TZ=Europe/Berlin`, `SECURE_COOKIES=false`.

### truenas-app.yaml

Same two services, but: absolute host paths `/mnt/tank/apps/cookbook/postgres` and `/mnt/tank/apps/cookbook/data`,
literal password placeholder `CHANGE_ME_DB_PASSWORD` (2 places), app uses `image: ghcr.io/pringsen/cookbook:latest`
with `pull_policy: always` (built by GitHub Actions, see CI below), env `PUID: "568"`, `PGID: "568"`,
`TZ: Europe/Vienna`, `ANTHROPIC_API_KEY: ""`, `SECURE_COOKIES: "false"`, port `8080:8000`.
`truenas-app-local.yaml` is identical except `image: cookbook:local`, `pull_policy: never` (image built on the NAS).

### TrueNAS install (summary; full guide in TRUENAS.md)

1. GitHub: push to `main` → Actions builds `ghcr.io/pringsen/cookbook:latest`. Make the package **public** once
   (Package settings → Change visibility); "Install via YAML" apps cannot use registry credentials. The repository
   itself stays private; the image holds no secrets.
2. Datasets: `tank/apps/cookbook` (Apps preset) with children `data` (Apps) and `postgres` (**Generic** preset, so
   Postgres can chown its folder).
3. Apps → Discover Apps → ⋮ → Install via YAML → name `cookbook` → paste `truenas-app.yaml` with pool name and
   password (`openssl rand -hex 24`) replaced → Save.
4. Open `http://<NAS-IP>:8080`, create the admin account, add the Anthropic key in Settings.
5. Update: wait for the green Actions build, then Stop/Start the app (pulls `latest`). Roll back by pinning a
   `sha-<commit>` tag. Data stays in `data` and `postgres`.
6. Backup: periodic recursive snapshots of `tank/apps/cookbook` + JSON export.
7. Without GitHub: copy the code to `tank/apps/cookbook/src`, `sudo docker build -t cookbook:local …/src`, install
   with `truenas-app-local.yaml`.

### CI

`.github/workflows/docker-publish.yml`: on push to `main`, `v*` tags and manual dispatch, build with buildx (GitHub
Actions cache) and push `ghcr.io/<owner>/<repo>` tags `latest` (default branch), the git tag, and `sha-<short>`, with
OCI labels (links the package to the repo), using `GITHUB_TOKEN` with `packages: write`. Platform linux/amd64.

---

## 12. Security notes

- Intended for a home network or behind a VPN / HTTPS reverse proxy. Not hardened for direct internet exposure
  (no rate limiting on login, URL import can fetch any URL the server can reach).
- The kitchen display link contains a random token and works without login (read-only: meals, shopping list,
  recent calendar entries). Only admins can create, rotate or turn it off.
- CSRF token on every POST; SameSite=Lax session cookie; scrypt password hashes; secret key kept in the data folder.
- The Anthropic key is stored in the database (Settings) or in the compose env; only admins can change it and
  the UI only shows its first 7 and last 4 characters.

---

## 13. Acceptance tests (run against `docker compose up`)

1. Fresh start redirects `/` → `/setup`; creating an account logs in and shows "Hello, <name>".
2. POST without/with wrong csrf → 400.
3. Create cookbook "Weeknight"; create recipe "Pancakes" (2 servings) with ingredients
   `200 g flour / 2 eggs / 300 ml milk / 1 ½ tbsp sugar / Topping: / 1 pinch salt`, assign to the cookbook.
4. `/recipes/{id}?servings=4` shows `400 g flour`, `4 eggs`, `3 tbsp sugar` and the "scaled" note; "Topping" is a header.
5. Add first three ingredients at 4 servings to shopping → "Added 3 items".
6. Log cooked on 2026-11-20 for "Anna, Tom" → visible in `/calendar?month=2026-11` and with `&guest=Anna`.
7. Plan the recipe for a day; add a note "Eating out"; planner shows both.
8. "Add this week's ingredients" → flour merged to **600 g**; adding "2 l milk" to existing 900 ml shows **2.9 l milk**.
9. `/shopping.txt` lists unchecked items; fetch toggle returns `{"checked": true}`.
10. URL import of a page with schema.org JSON-LD (`@graph`, HowToStep list) pre-fills title, `150 g guanciale, diced`
    and steps.
11. Without an API key the photo tab shows "needs an Anthropic API key"; with a mocked AI the draft form shows the
    transcribed recipe and saving keeps the photo.
12. Admin can add a user; `/export.json` contains the recipe; unknown recipe → 404 page; deleting a recipe flashes "Deleted".
13. Logged-out client is redirected to `/login`. After `docker compose down && up`, data persists.
14. `/recipes/{id}/cook` shows "Ingredients"; `?step=2&servings=8` shows "Step 2 of 4" with doubled amounts;
    `?step=99` is clamped to the last step.
15. `/display/tablet?next=/recipes/2` returns the page with `body.mode-tablet`; `/display/epaper` gives `mode-epaper`.
16. Admin creates a display link; an anonymous client opens `/kitchen?token=…&display=epaper` (200, e-paper mode,
    shopping list, refresh meta); a wrong token gives 403; no token redirects to login.
17. Create a bread recipe "Bread rolls": 14 pieces × 75 g; flours Bread flour 90 % (levain 100 %), Whole wheat 10 %
    (levain 0 %); others Water 65 % (levain 100 %, liquid), Salt 3 %, Olive oil 3 %; levain 50 %
    (total 171 %). The page shows flour **614 g**, levain **307 g** (153.5 g flour + 153.5 g water), final water
    245.6 g, hydration 65 %. `?servings=28&piece_weight=75` shows total 2100 g. "Add to shopping list" adds grams.
18. `/levain?target=45&s=1&w=3&f=5&h=100` shows 5 g starter, 15 g water, 25 g flour, 63.6 % hydration;
    `h=60` shows 60 %. In a browser, typing a new hydration updates the result without a button. Enabling the build in a bread recipe sets the levain water to the build hydration.
19. Starting a v1.2 database with v1.3 adds `recipes.kind` and `recipes.bread`; existing recipes open as standard.
20. E-paper mode: `/recipes/{id}/cook` shows the whole recipe (`cookpage`, "One step at a time"); `?step=2&view=steps`
    shows "Step 2 of n" and its links keep `view=steps`. Standard mode: `/recipes/{id}/cook` is step 0 with a
    "Whole recipe" button; `?view=page` shows the whole recipe. Kitchen display at 1650 × 1240 px in e-paper mode
    shows 7 days and "Cooking today"; at 600 × 800 px 3 days and no "Cooking today".

---

## 14. Known limitations / ideas for later

- English UI only (German translation is easy to add: all text is in the templates).
- Only additive migrations (new columns via `NEW_COLUMNS`); add Alembic before changing existing columns.
- No drag-and-drop in the planner, no recipe sharing links, no nutrition data, no offline mode / PWA.
- E-paper mode targets e-readers with a web browser. Displays that only show images (e.g. TRMNL, Inkplate)
  would need a server-rendered PNG of `/kitchen`, which is not included.
- Screen wake lock needs HTTPS on most browsers except on `localhost`; over plain HTTP on the LAN the iPad may
  still dim (set Auto-Lock to "Never" while cooking, or use HTTPS via a reverse proxy).
- Photo import with a real API key and link import from real recipe sites were not exercised in the v1 test
  environment (no key, no outbound access); both are covered by mocked/sample tests.
