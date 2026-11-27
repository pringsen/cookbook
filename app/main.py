import calendar as cal
import io
import json
import logging
import secrets
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps
from sqlalchemy import func, or_, select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import ai, bread, config, importer
from . import ingredients as ing
from .auth import hash_password, verify_password
from .db import (
    CookLog, Cookbook, MealPlan, Recipe, SessionLocal, ShoppingItem, User, get_setting, init_db,
    set_setting,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cookbook")

BASE = Path(__file__).parent
MEALS = ["breakfast", "lunch", "dinner", "snack"]

config.ensure_dirs()
for _attempt in range(30):  # the database container may still be starting
    try:
        init_db()
        break
    except Exception as e:  # noqa: BLE001
        log.warning("Database not ready (%s), retrying…", e.__class__.__name__)
        import time
        time.sleep(2)
else:
    raise SystemExit("Could not connect to the database. Check DATABASE_URL / POSTGRES_PASSWORD.")

app = FastAPI(title="Cookbook", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware, secret_key=config.secret_key(), session_cookie="cookbook_session",
    max_age=60 * 60 * 24 * 60, same_site="lax", https_only=config.SECURE_COOKIES,
)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.mount("/media", StaticFiles(directory=config.UPLOAD_DIR), name="media")
templates = Jinja2Templates(directory=BASE / "templates")


# ---------------------------------------------------------------- helpers

def fmt_minutes(m):
    if not m:
        return ""
    h, mi = divmod(int(m), 60)
    return f"{h} h {mi} min" if h and mi else (f"{h} h" if h else f"{mi} min")


templates.env.filters["minutes"] = fmt_minutes
templates.env.filters["qty"] = ing.fmt_qty
templates.env.globals["is_header"] = ing.is_header
templates.env.globals["header_text"] = ing.header_text
templates.env.globals["amount"] = ing.display_amount
templates.env.filters["grams"] = bread.g


class Redirect(Exception):
    def __init__(self, url: str):
        self.url = url


@app.exception_handler(Redirect)
async def _redirect_handler(request: Request, exc: Redirect):
    return RedirectResponse(exc.url, status_code=303)


def go(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def flash(request: Request, msg: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", []).append([kind, msg])


def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = request.session["csrf"] = secrets.token_urlsafe(24)
    return tok


async def read_form(request: Request):
    form = await request.form()
    sent = form.get("csrf") or request.headers.get("x-csrf-token")
    if not sent or not secrets.compare_digest(str(sent), request.session.get("csrf", "")):
        raise HTTPException(400, "Your session expired. Go back, reload the page and try again.")
    return form


def db_session():
    return SessionLocal()


def current_user(request: Request, db) -> User:
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if not user:
        if not db.scalar(select(func.count(User.id))):
            raise Redirect("/setup")
        raise Redirect("/login?next=" + request.url.path)
    return user


def render(request: Request, name: str, ctx: dict | None = None, status: int = 200, user=None):
    ctx = dict(ctx or {})
    ctx["request"] = request
    ctx["user"] = user
    ctx["csrf"] = csrf_token(request)
    ctx["flashes"] = request.session.pop("flash", [])
    ctx["today"] = date.today()
    ctx.setdefault("mode", display_mode(request))
    return templates.TemplateResponse(request, name, ctx, status_code=status)


DISPLAY_MODES = ("standard", "tablet", "epaper")


def display_mode(request: Request) -> str:
    """Per-device display mode, kept in a cookie so a kitchen tablet and a phone can differ."""
    m = request.query_params.get("display") or request.cookies.get("cookbook_display", "standard")
    return m if m in DISPLAY_MODES else "standard"


def to_int(v, default=None):
    try:
        return int(str(v).strip()) if v not in (None, "") else default
    except ValueError:
        return default


def _float(v):
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def to_date(v, default=None):
    try:
        return date.fromisoformat(str(v)) if v else default
    except ValueError:
        return default


def save_image(data: bytes) -> str:
    """Store an uploaded image (resized, EXIF-rotated) and return its file name."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((1600, 1600))
    name = f"{uuid.uuid4().hex}.jpg"
    img.save(config.UPLOAD_DIR / name, "JPEG", quality=85)
    return name


def delete_image(name: str) -> None:
    if name and "/" not in name and ".." not in name:
        try:
            (config.UPLOAD_DIR / name).unlink(missing_ok=True)
        except OSError:
            pass


def ai_settings(db) -> tuple[str, str]:
    key = config.ANTHROPIC_API_KEY or get_setting(db, "anthropic_api_key")
    model = config.AI_MODEL or get_setting(db, "ai_model") or config.DEFAULT_AI_MODEL
    return key, model


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def add_to_shopping(db, line: str, factor: float = 1.0, note: str = "") -> None:
    if ing.is_header(line):
        return
    p = ing.parse(line)
    qty, unit = ing.to_base(p.quantity * factor if p.quantity is not None else None, p.unit)
    key = ing.normalize_name(p.name)
    existing = db.scalars(select(ShoppingItem).where(ShoppingItem.checked.is_(False))).all()
    for item in existing:
        if ing.normalize_name(item.name) == key and item.unit == unit and \
                (item.quantity is None) == (qty is None):
            if qty is not None:
                item.quantity = (item.quantity or 0) + qty
            if note and note not in item.note:
                item.note = f"{item.note}, {note}" if item.note else note
            return
    pos = (db.scalar(select(func.max(ShoppingItem.position))) or 0) + 1
    db.add(ShoppingItem(name=p.name, quantity=qty, unit=unit, note=note, position=pos))


# ---------------------------------------------------------------- auth

@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request):
    with db_session() as db:
        if db.scalar(select(func.count(User.id))):
            return go("/login")
    return render(request, "setup.html")


@app.post("/setup")
async def setup_submit(request: Request):
    form = await read_form(request)
    with db_session() as db:
        if db.scalar(select(func.count(User.id))):
            return go("/login")
        username = str(form.get("username", "")).strip().lower()
        pw = str(form.get("password", ""))
        if not username or len(pw) < 8:
            flash(request, "Choose a username and a password with at least 8 characters.", "error")
            return go("/setup")
        u = User(username=username, display_name=str(form.get("display_name", "")).strip(),
                 password_hash=hash_password(pw), is_admin=True)
        db.add(u)
        db.commit()
        request.session["uid"] = u.id
    flash(request, "Welcome! Your cookbook is ready.")
    return go("/")


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/"):
    with db_session() as db:
        if not db.scalar(select(func.count(User.id))):
            return go("/setup")
    return render(request, "login.html", {"next": next})


@app.post("/login")
async def login_submit(request: Request):
    form = await read_form(request)
    nxt = str(form.get("next") or "/")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    with db_session() as db:
        u = db.scalar(select(User).where(User.username == str(form.get("username", "")).strip().lower()))
        if not u or not verify_password(str(form.get("password", "")), u.password_hash):
            flash(request, "Wrong username or password.", "error")
            return go("/login?next=" + nxt)
        request.session["uid"] = u.id
    return go(nxt)


@app.post("/logout")
async def logout(request: Request):
    await read_form(request)
    request.session.clear()
    return go("/login")


# ---------------------------------------------------------------- home

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with db_session() as db:
        user = current_user(request, db)
        today = date.today()
        ws = week_start(today)
        plan = db.scalars(select(MealPlan).where(MealPlan.day >= today, MealPlan.day < today + timedelta(days=7))
                          .order_by(MealPlan.day)).all()
        recent = db.scalars(select(Recipe).order_by(Recipe.created_at.desc()).limit(8)).all()
        cooked = db.scalars(select(CookLog).order_by(CookLog.cooked_on.desc(), CookLog.id.desc()).limit(6)).all()
        counts = {
            "recipes": db.scalar(select(func.count(Recipe.id))),
            "cookbooks": db.scalar(select(func.count(Cookbook.id))),
            "shopping": db.scalar(select(func.count(ShoppingItem.id)).where(ShoppingItem.checked.is_(False))),
        }
        plan_sorted = sorted(plan, key=lambda p: (p.day, MEALS.index(p.meal) if p.meal in MEALS else 9))
        return render(request, "home.html", {"plan": plan_sorted, "recent": recent, "cooked": cooked,
                                             "counts": counts, "week": ws}, user=user)


# ---------------------------------------------------------------- recipes

@app.get("/recipes", response_class=HTMLResponse)
def recipe_list(request: Request, q: str = "", tag: str = "", fav: int = 0, sort: str = "title", kind: str = ""):
    with db_session() as db:
        user = current_user(request, db)
        stmt = select(Recipe)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(Recipe.title.ilike(like), Recipe.tags.ilike(like),
                                  Recipe.ingredients.ilike(like), Recipe.description.ilike(like)))
        if tag:
            stmt = stmt.where(Recipe.tags.ilike(f"%{tag}%"))
        if fav:
            stmt = stmt.where(Recipe.favorite.is_(True))
        if kind == "bread":
            stmt = stmt.where(Recipe.kind == "bread")
        order = {"new": Recipe.created_at.desc(), "rating": Recipe.rating.desc().nulls_last()}.get(sort, Recipe.title)
        recipes = db.scalars(stmt.order_by(order, Recipe.title)).all()
        if tag:  # exact tag match after the coarse SQL filter
            recipes = [r for r in recipes if tag.lower() in (t.lower() for t in r.tag_list)]
        all_tags = sorted({t for r in db.scalars(select(Recipe)).all() for t in r.tag_list}, key=str.lower)
        return render(request, "recipes.html", {"recipes": recipes, "q": q, "tag": tag, "fav": fav,
                                                "sort": sort, "all_tags": all_tags, "kind": kind}, user=user)


def recipe_or_404(db, rid: int) -> Recipe:
    r = db.get(Recipe, rid)
    if not r:
        raise HTTPException(404, "Recipe not found")
    return r


@app.get("/recipes/new", response_class=HTMLResponse)
def recipe_new(request: Request, cookbook: int | None = None, kind: str = "standard"):
    with db_session() as db:
        user = current_user(request, db)
        cookbooks = db.scalars(select(Cookbook).order_by(Cookbook.name)).all()
        return render(request, "recipe_form.html", {
            "recipe": None, "draft": None, "cookbooks": cookbooks,
            "selected_cookbooks": {cookbook} if cookbook else set(),
            "kind": "bread" if kind == "bread" else "standard", "bread_spec": bread.default_spec()}, user=user)


def apply_form(db, r: Recipe, form) -> None:
    r.title = str(form.get("title", "")).strip()[:300] or "Untitled recipe"
    r.description = str(form.get("description", "")).strip()
    r.servings = to_int(form.get("servings"))
    r.prep_minutes = to_int(form.get("prep_minutes"))
    r.cook_minutes = to_int(form.get("cook_minutes"))
    r.ingredients = "\n".join(ing.lines(str(form.get("ingredients", ""))))
    r.instructions = "\n".join(ing.lines(str(form.get("instructions", ""))))
    r.notes = str(form.get("notes", "")).strip()
    r.tags = ", ".join(t.strip() for t in str(form.get("tags", "")).split(",") if t.strip())[:500]
    r.source_url = str(form.get("source_url", "")).strip()[:1000]
    r.rating = to_int(form.get("rating"))
    r.kind = "bread" if form.get("kind") == "bread" else "standard"
    if r.kind == "bread":
        spec = bread.from_form(form)
        res = bread.compute(spec)
        r.bread = bread.dump(spec)
        r.servings = spec["pieces"]
        r.ingredients = bread.ingredients_text(res)  # totals, for search / shopping list / cook mode
    ids = [to_int(x) for x in form.getlist("cookbooks")]
    r.cookbooks = list(db.scalars(select(Cookbook).where(Cookbook.id.in_([i for i in ids if i])))) if ids else []


async def apply_image(r: Recipe, form) -> None:
    upload = form.get("image")
    if form.get("remove_image"):
        delete_image(r.image)
        r.image = ""
    if upload is not None and getattr(upload, "filename", ""):
        data = await upload.read()
        if data:
            try:
                name = save_image(data)
            except Exception:
                raise HTTPException(400, "That file doesn't look like an image.")
            delete_image(r.image)
            r.image = name
    elif form.get("image_existing") and not r.image:
        name = str(form.get("image_existing"))
        if "/" not in name and (config.UPLOAD_DIR / name).exists():
            r.image = name


@app.post("/recipes/new")
async def recipe_create(request: Request):
    form = await read_form(request)
    with db_session() as db:
        user = current_user(request, db)
        r = Recipe(created_by_id=user.id)
        apply_form(db, r, form)
        await apply_image(r, form)
        db.add(r)
        db.commit()
        flash(request, f"Saved “{r.title}”.")
        return go(f"/recipes/{r.id}")


def bread_result(r: Recipe, servings=None, piece_weight=None, total=None):
    """Bread calculation for a recipe, optionally resized (pieces, piece weight or total dough weight)."""
    spec = bread.load(r.bread)
    pw = piece_weight if piece_weight else None
    if pw is None and not total and spec.get("total_weight"):
        # recipe saved with a target total: keep the per-piece weight when only the count changes
        pw = spec["total_weight"] / max(1, spec.get("pieces") or 1)
    return bread.compute(spec, pieces=servings, piece_weight=pw, total_weight=total)


@app.get("/recipes/{rid}", response_class=HTMLResponse)
def recipe_view(request: Request, rid: int, servings: int | None = None, piece_weight: float | None = None,
                total: float | None = None):
    with db_session() as db:
        user = current_user(request, db)
        r = recipe_or_404(db, rid)
        factor = 1.0
        res = None
        if r.kind == "bread":
            res = bread_result(r, servings, piece_weight, total)
            lines = ing.lines(bread.ingredients_text(res))
            servings = res.pieces
        else:
            if servings and r.servings:
                factor = servings / r.servings
            lines = [ing.scale_line(l, factor) for l in ing.lines(r.ingredients)]
        cookbooks = db.scalars(select(Cookbook).order_by(Cookbook.name)).all()
        return render(request, "recipe.html", {
            "r": r, "lines": lines, "servings": servings or r.servings, "factor": factor, "res": res,
            "piece_weight": piece_weight, "total": total,
            "cookbooks": cookbooks, "logs": r.logs[:10], "times_cooked": len(r.logs),
            "meals": MEALS}, user=user)


@app.get("/recipes/{rid}/edit", response_class=HTMLResponse)
def recipe_edit(request: Request, rid: int):
    with db_session() as db:
        user = current_user(request, db)
        r = recipe_or_404(db, rid)
        cookbooks = db.scalars(select(Cookbook).order_by(Cookbook.name)).all()
        return render(request, "recipe_form.html", {
            "recipe": r, "draft": None, "cookbooks": cookbooks,
            "selected_cookbooks": {c.id for c in r.cookbooks},
            "kind": r.kind, "bread_spec": bread.load(r.bread)}, user=user)


@app.post("/recipes/{rid}/edit")
async def recipe_update(request: Request, rid: int):
    form = await read_form(request)
    with db_session() as db:
        current_user(request, db)
        r = recipe_or_404(db, rid)
        apply_form(db, r, form)
        await apply_image(r, form)
        db.commit()
        flash(request, "Changes saved.")
        return go(f"/recipes/{r.id}")


@app.post("/recipes/{rid}/delete")
async def recipe_delete(request: Request, rid: int):
    await read_form(request)
    with db_session() as db:
        current_user(request, db)
        r = recipe_or_404(db, rid)
        delete_image(r.image)
        title = r.title
        for l in r.logs:  # keep the name in the cooking calendar
            l.title = l.title or title
        db.delete(r)
        db.commit()
    flash(request, f"Deleted “{title}”.")
    return go("/recipes")


@app.post("/recipes/{rid}/favorite")
async def recipe_favorite(request: Request, rid: int):
    await read_form(request)
    with db_session() as db:
        current_user(request, db)
        r = recipe_or_404(db, rid)
        r.favorite = not r.favorite
        db.commit()
        return go(f"/recipes/{rid}")


@app.post("/recipes/{rid}/cookbooks")
async def recipe_cookbooks(request: Request, rid: int):
    form = await read_form(request)
    with db_session() as db:
        current_user(request, db)
        r = recipe_or_404(db, rid)
        ids = [to_int(x) for x in form.getlist("cookbooks")]
        r.cookbooks = list(db.scalars(select(Cookbook).where(Cookbook.id.in_([i for i in ids if i])))) if ids else []
        db.commit()
        flash(request, "Cookbooks updated.")
        return go(f"/recipes/{rid}")


@app.post("/recipes/{rid}/shopping")
async def recipe_to_shopping(request: Request, rid: int):
    form = await read_form(request)
    with db_session() as db:
        current_user(request, db)
        r = recipe_or_404(db, rid)
        picked = {to_int(x) for x in form.getlist("item")}
        servings = to_int(form.get("servings"))
        factor = servings / r.servings if servings and r.servings else 1.0
        all_lines = ing.lines(r.ingredients)
        if r.kind == "bread":  # amounts already resized by the bread calculator
            res = bread_result(r, servings, _float(form.get("piece_weight")), _float(form.get("total")))
            all_lines, factor = ing.lines(bread.ingredients_text(res)), 1.0
        n = 0
        for i, line in enumerate(all_lines):
            if i in picked and not ing.is_header(line):
                add_to_shopping(db, line, factor, r.title)
                n += 1
        db.commit()
    flash(request, f"Added {n} item{'s' if n != 1 else ''} to the shopping list.")
    return go(f"/recipes/{rid}" + (f"?servings={servings}" if servings else ""))


@app.post("/recipes/{rid}/cooked")
async def recipe_cooked(request: Request, rid: int):
    form = await read_form(request)
    with db_session() as db:
        user = current_user(request, db)
        r = recipe_or_404(db, rid)
        db.add(CookLog(recipe_id=r.id, cooked_on=to_date(form.get("cooked_on"), date.today()),
                       guests=str(form.get("guests", "")).strip(), notes=str(form.get("notes", "")).strip(),
                       rating=to_int(form.get("rating")), user_id=user.id))
        db.commit()
    flash(request, "Added to your cooking calendar.")
    return go(f"/recipes/{rid}")


@app.post("/recipes/{rid}/plan")
async def recipe_plan(request: Request, rid: int):
    form = await read_form(request)
    with db_session() as db:
        current_user(request, db)
        r = recipe_or_404(db, rid)
        day = to_date(form.get("day"), date.today())
        meal = str(form.get("meal", "dinner"))
        db.add(MealPlan(day=day, meal=meal if meal in MEALS else "dinner", recipe_id=r.id,
                        servings=to_int(form.get("servings"))))
        db.commit()
    flash(request, f"Planned for {day.strftime('%a %d %b')}.")
    return go(f"/planner?week={week_start(day).isoformat()}")


# ---------------------------------------------------------------- import

@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request, tab: str = "photo"):
    with db_session() as db:
        user = current_user(request, db)
        key, model = ai_settings(db)
        return render(request, "import.html", {"tab": tab, "ai_ready": bool(key), "model": model}, user=user)


def draft_form(request, db, user, draft: importer.RecipeDraft, image_name: str = "", note: str = ""):
    cookbooks = db.scalars(select(Cookbook).order_by(Cookbook.name)).all()
    return render(request, "recipe_form.html", {
        "recipe": None, "draft": draft, "image_existing": image_name, "cookbooks": cookbooks,
        "kind": "standard", "bread_spec": bread.default_spec(),
        "selected_cookbooks": set(), "import_note": note}, user=user)


@app.post("/import/url")
async def import_url(request: Request):
    form = await read_form(request)
    url = str(form.get("url", "")).strip()
    use_ai = bool(form.get("use_ai"))
    with db_session() as db:
        user = current_user(request, db)
        key, model = ai_settings(db)
        try:
            draft, html = await run_in_threadpool(importer.import_url, url)
        except importer.ImportError_ as e:
            flash(request, str(e), "error")
            return go("/import?tab=url")
        note = "Imported from the page's recipe data. Check it and save."
        if (not draft or not draft.is_useful()) and use_ai and key:
            try:
                draft = await run_in_threadpool(ai.extract_from_text, key, model, importer.page_text(html), url)
                note = "This page had no structured recipe data, so the AI read the page text. Please check it carefully."
            except ai.AIError as e:
                flash(request, str(e), "error")
                return go("/import?tab=url")
        if not draft or not draft.is_useful():
            msg = "No recipe data found on that page."
            if key and not use_ai:
                msg += " Tick “Let AI read the page” and try again."
            elif not key:
                msg += " With an Anthropic API key (Settings) the AI can read pages like this."
            flash(request, msg, "error")
            return go("/import?tab=url")
        image_name = ""
        data = await run_in_threadpool(importer.download_image, draft.image_url)
        if data:
            try:
                image_name = save_image(data)
            except Exception:
                image_name = ""
        return draft_form(request, db, user, draft, image_name, note)


@app.post("/import/photo")
async def import_photo(request: Request):
    form = await read_form(request)
    files = [f for f in form.getlist("photos") if getattr(f, "filename", "")]
    hint = str(form.get("hint", "")).strip()
    with db_session() as db:
        user = current_user(request, db)
        key, model = ai_settings(db)
        if not files:
            flash(request, "Choose at least one photo.", "error")
            return go("/import?tab=photo")
        blobs = [await f.read() for f in files]
        blobs = [b for b in blobs if b]
        if sum(len(b) for b in blobs) > 60 * 1024 * 1024:
            flash(request, "Those photos are too large together (max 60 MB).", "error")
            return go("/import?tab=photo")
        try:
            draft = await run_in_threadpool(ai.extract_from_images, key, model, blobs, hint)
        except ai.AIError as e:
            flash(request, str(e), "error")
            return go("/import?tab=photo")
        image_name = ""
        if form.get("keep_photo"):
            try:
                image_name = save_image(blobs[0])
            except Exception:
                pass
        return draft_form(request, db, user, draft, image_name,
                          "The AI read your photo. Check quantities and steps, then save.")


# ---------------------------------------------------------------- cookbooks

@app.get("/cookbooks", response_class=HTMLResponse)
def cookbook_list(request: Request):
    with db_session() as db:
        user = current_user(request, db)
        books = db.scalars(select(Cookbook).order_by(Cookbook.name)).all()
        return render(request, "cookbooks.html", {"books": books}, user=user)


@app.post("/cookbooks/new")
async def cookbook_create(request: Request):
    form = await read_form(request)
    with db_session() as db:
        current_user(request, db)
        name = str(form.get("name", "")).strip()
        if not name:
            flash(request, "Give the cookbook a name.", "error")
            return go("/cookbooks")
        b = Cookbook(name=name[:200], description=str(form.get("description", "")).strip(),
                     color=str(form.get("color") or "#c2410c")[:20])
        db.add(b)
        db.commit()
        return go(f"/cookbooks/{b.id}")


@app.get("/cookbooks/{bid}", response_class=HTMLResponse)
def cookbook_view(request: Request, bid: int):
    with db_session() as db:
        user = current_user(request, db)
        b = db.get(Cookbook, bid)
        if not b:
            raise HTTPException(404, "Cookbook not found")
        in_book = {r.id for r in b.recipes}
        others = [r for r in db.scalars(select(Recipe).order_by(Recipe.title)).all() if r.id not in in_book]
        return render(request, "cookbook.html", {"b": b, "others": others}, user=user)


@app.post("/cookbooks/{bid}/edit")
async def cookbook_update(request: Request, bid: int):
    form = await read_form(request)
    with db_session() as db:
        current_user(request, db)
        b = db.get(Cookbook, bid)
        if not b:
            raise HTTPException(404)
        b.name = str(form.get("name", b.name)).strip()[:200] or b.name
        b.description = str(form.get("description", "")).strip()
        b.color = str(form.get("color") or b.color)[:20]
        db.commit()
    flash(request, "Cookbook updated.")
    return go(f"/cookbooks/{bid}")


@app.post("/cookbooks/{bid}/add")
async def cookbook_add(request: Request, bid: int):
    form = await read_form(request)
    with db_session() as db:
        current_user(request, db)
        b = db.get(Cookbook, bid)
        ids = [to_int(x) for x in form.getlist("recipe")]
        for r in db.scalars(select(Recipe).where(Recipe.id.in_([i for i in ids if i]))):
            if r not in b.recipes:
                b.recipes.append(r)
        db.commit()
    return go(f"/cookbooks/{bid}")


@app.post("/cookbooks/{bid}/remove/{rid}")
async def cookbook_remove(request: Request, bid: int, rid: int):
    await read_form(request)
    with db_session() as db:
        current_user(request, db)
        b = db.get(Cookbook, bid)
        b.recipes = [r for r in b.recipes if r.id != rid]
        db.commit()
    return go(f"/cookbooks/{bid}")


@app.post("/cookbooks/{bid}/delete")
async def cookbook_delete(request: Request, bid: int):
    await read_form(request)
    with db_session() as db:
        current_user(request, db)
        b = db.get(Cookbook, bid)
        if b:
            db.delete(b)
            db.commit()
    flash(request, "Cookbook deleted. Its recipes are still in your collection.")
    return go("/cookbooks")


# ---------------------------------------------------------------- cooking calendar

@app.get("/calendar", response_class=HTMLResponse)
def calendar_view(request: Request, month: str = "", guest: str = ""):
    with db_session() as db:
        user = current_user(request, db)
        try:
            first = datetime.strptime(month, "%Y-%m").date() if month else date.today().replace(day=1)
        except ValueError:
            first = date.today().replace(day=1)
        days_in = cal.monthrange(first.year, first.month)[1]
        last = first.replace(day=days_in)
        stmt = select(CookLog).where(CookLog.cooked_on >= first, CookLog.cooked_on <= last)
        if guest:
            stmt = stmt.where(CookLog.guests.ilike(f"%{guest}%"))
        logs = db.scalars(stmt.order_by(CookLog.cooked_on, CookLog.id)).all()
        by_day: dict[date, list] = {}
        for l in logs:
            by_day.setdefault(l.cooked_on, []).append(l)
        weeks = cal.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
        prev_m = (first - timedelta(days=1)).replace(day=1)
        next_m = last + timedelta(days=1)
        recipes = db.scalars(select(Recipe).order_by(Recipe.title)).all()
        # Everyone you have cooked for, for quick filtering / autocomplete.
        people = sorted({p.strip() for (g,) in db.execute(select(CookLog.guests)) for p in (g or "").split(",")
                         if p.strip()}, key=str.lower)
        return render(request, "calendar.html", {
            "first": first, "weeks": weeks, "by_day": by_day, "logs": logs, "prev_m": prev_m,
            "next_m": next_m, "recipes": recipes, "people": people, "guest": guest}, user=user)


@app.post("/calendar/new")
async def calendar_add(request: Request):
    form = await read_form(request)
    with db_session() as db:
        user = current_user(request, db)
        rid = to_int(form.get("recipe_id"))
        title = str(form.get("title", "")).strip()
        if not rid and not title:
            flash(request, "Pick a recipe or type what you cooked.", "error")
            return go("/calendar")
        d = to_date(form.get("cooked_on"), date.today())
        db.add(CookLog(recipe_id=rid, title=title, cooked_on=d, guests=str(form.get("guests", "")).strip(),
                       notes=str(form.get("notes", "")).strip(), rating=to_int(form.get("rating")),
                       user_id=user.id))
        db.commit()
    return go(f"/calendar?month={d.strftime('%Y-%m')}")


@app.post("/calendar/{lid}/delete")
async def calendar_delete(request: Request, lid: int):
    await read_form(request)
    with db_session() as db:
        current_user(request, db)
        l = db.get(CookLog, lid)
        m = l.cooked_on.strftime("%Y-%m") if l else ""
        if l:
            db.delete(l)
            db.commit()
    return go(f"/calendar?month={m}")


# ---------------------------------------------------------------- meal planner

@app.get("/planner", response_class=HTMLResponse)
def planner(request: Request, week: str = ""):
    with db_session() as db:
        user = current_user(request, db)
        ws = week_start(to_date(week, date.today()))
        days = [ws + timedelta(days=i) for i in range(7)]
        entries = db.scalars(select(MealPlan).where(MealPlan.day >= ws, MealPlan.day < ws + timedelta(days=7))
                             .order_by(MealPlan.id)).all()
        grid: dict[tuple, list] = {}
        for e in entries:
            grid.setdefault((e.day, e.meal), []).append(e)
        recipes = db.scalars(select(Recipe).order_by(Recipe.title)).all()
        return render(request, "planner.html", {
            "days": days, "grid": grid, "meals": MEALS, "ws": ws, "recipes": recipes,
            "prev_w": ws - timedelta(days=7), "next_w": ws + timedelta(days=7),
            "has_entries": bool(entries)}, user=user)


@app.post("/planner/add")
async def planner_add(request: Request):
    form = await read_form(request)
    with db_session() as db:
        current_user(request, db)
        day = to_date(form.get("day"), date.today())
        rid = to_int(form.get("recipe_id"))
        note = str(form.get("note", "")).strip()
        meal = str(form.get("meal", "dinner"))
        if rid or note:
            db.add(MealPlan(day=day, meal=meal if meal in MEALS else "dinner", recipe_id=rid, note=note,
                            servings=to_int(form.get("servings"))))
            db.commit()
    return go(f"/planner?week={week_start(day).isoformat()}")


@app.post("/planner/{pid}/delete")
async def planner_delete(request: Request, pid: int):
    await read_form(request)
    with db_session() as db:
        current_user(request, db)
        e = db.get(MealPlan, pid)
        ws = week_start(e.day).isoformat() if e else ""
        if e:
            db.delete(e)
            db.commit()
    return go(f"/planner?week={ws}")


@app.post("/planner/{pid}/move")
async def planner_move(request: Request, pid: int):
    form = await read_form(request)
    with db_session() as db:
        current_user(request, db)
        e = db.get(MealPlan, pid)
        if e:
            e.day = to_date(form.get("day"), e.day)
            meal = str(form.get("meal", e.meal))
            e.meal = meal if meal in MEALS else e.meal
            db.commit()
            return go(f"/planner?week={week_start(e.day).isoformat()}")
    return go("/planner")


@app.post("/planner/{pid}/cooked")
async def planner_cooked(request: Request, pid: int):
    form = await read_form(request)
    with db_session() as db:
        user = current_user(request, db)
        e = db.get(MealPlan, pid)
        if not e:
            return go("/planner")
        e.cooked = True
        db.add(CookLog(recipe_id=e.recipe_id, title="" if e.recipe_id else e.note, cooked_on=e.day,
                       guests=str(form.get("guests", "")).strip(), user_id=user.id))
        db.commit()
        flash(request, f"Logged “{e.label}” in your cooking calendar.")
        return go(f"/planner?week={week_start(e.day).isoformat()}")


@app.post("/planner/shopping")
async def planner_shopping(request: Request):
    form = await read_form(request)
    with db_session() as db:
        current_user(request, db)
        ws = week_start(to_date(form.get("week"), date.today()))
        entries = db.scalars(select(MealPlan).where(MealPlan.day >= ws, MealPlan.day < ws + timedelta(days=7),
                                                    MealPlan.recipe_id.is_not(None))).all()
        n = 0
        for e in entries:
            r = e.recipe
            factor = e.servings / r.servings if e.servings and r.servings else 1.0
            for line in ing.lines(r.ingredients):
                if not ing.is_header(line):
                    add_to_shopping(db, line, factor, r.title)
                    n += 1
        db.commit()
    flash(request, f"Added ingredients from {len(entries)} planned meal{'s' if len(entries) != 1 else ''} "
                   f"to the shopping list ({n} lines, duplicates merged).")
    return go("/shopping")


# ---------------------------------------------------------------- shopping list

@app.get("/shopping", response_class=HTMLResponse)
def shopping(request: Request):
    with db_session() as db:
        user = current_user(request, db)
        items = db.scalars(select(ShoppingItem).order_by(ShoppingItem.checked, ShoppingItem.position)).all()
        return render(request, "shopping.html", {"items": items}, user=user)


@app.post("/shopping/add")
async def shopping_add(request: Request):
    form = await read_form(request)
    with db_session() as db:
        current_user(request, db)
        for line in ing.lines(str(form.get("text", ""))):
            add_to_shopping(db, line)
        db.commit()
    return go("/shopping")


@app.post("/shopping/{iid}/toggle")
async def shopping_toggle(request: Request, iid: int):
    await read_form(request)
    with db_session() as db:
        current_user(request, db)
        it = db.get(ShoppingItem, iid)
        if it:
            it.checked = not it.checked
            db.commit()
        if request.headers.get("x-requested-with") == "fetch":
            return JSONResponse({"checked": bool(it and it.checked)})
    return go("/shopping")


@app.post("/shopping/{iid}/delete")
async def shopping_delete(request: Request, iid: int):
    await read_form(request)
    with db_session() as db:
        current_user(request, db)
        it = db.get(ShoppingItem, iid)
        if it:
            db.delete(it)
            db.commit()
    return go("/shopping")


@app.post("/shopping/clear")
async def shopping_clear(request: Request):
    form = await read_form(request)
    with db_session() as db:
        current_user(request, db)
        stmt = select(ShoppingItem)
        if form.get("what") != "all":
            stmt = stmt.where(ShoppingItem.checked.is_(True))
        for it in db.scalars(stmt):
            db.delete(it)
        db.commit()
    return go("/shopping")


@app.get("/shopping.txt")
def shopping_text(request: Request):
    with db_session() as db:
        current_user(request, db)
        items = db.scalars(select(ShoppingItem).where(ShoppingItem.checked.is_(False))
                           .order_by(ShoppingItem.position)).all()
        text = "\n".join(f"- {' '.join(x for x in [ing.display_amount(i.quantity, i.unit), i.name] if x)}" for i in items)
        return Response(text + "\n", media_type="text/plain; charset=utf-8")


# ---------------------------------------------------------------- settings

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    with db_session() as db:
        user = current_user(request, db)
        key, model = ai_settings(db)
        users = db.scalars(select(User).order_by(User.username)).all() if user.is_admin else []
        return render(request, "settings.html", {
            "has_key": bool(key), "key_from_env": bool(config.ANTHROPIC_API_KEY),
            "key_hint": (key[:7] + "…" + key[-4:]) if len(key) > 12 else "",
            "model": model, "model_from_env": bool(config.AI_MODEL), "default_model": config.DEFAULT_AI_MODEL,
            "users": users, "kiosk_token": get_setting(db, "kiosk_token") if user.is_admin else "",
            "base_url": str(request.base_url).rstrip("/")}, user=user)


@app.post("/settings/ai")
async def settings_ai(request: Request):
    form = await read_form(request)
    with db_session() as db:
        user = current_user(request, db)
        if not user.is_admin:
            raise HTTPException(403, "Only an admin can change AI settings.")
        if form.get("clear_key"):
            set_setting(db, "anthropic_api_key", "")
        elif str(form.get("api_key", "")).strip():
            set_setting(db, "anthropic_api_key", str(form.get("api_key")).strip())
        set_setting(db, "ai_model", str(form.get("model", "")).strip())
        db.commit()
    flash(request, "AI settings saved.")
    return go("/settings")


@app.post("/settings/password")
async def settings_password(request: Request):
    form = await read_form(request)
    with db_session() as db:
        user = current_user(request, db)
        if not verify_password(str(form.get("current", "")), user.password_hash):
            flash(request, "Your current password is not correct.", "error")
        elif len(str(form.get("new", ""))) < 8:
            flash(request, "The new password needs at least 8 characters.", "error")
        else:
            user.password_hash = hash_password(str(form.get("new")))
            db.commit()
            flash(request, "Password changed.")
    return go("/settings")


@app.post("/settings/users/new")
async def settings_user_new(request: Request):
    form = await read_form(request)
    with db_session() as db:
        user = current_user(request, db)
        if not user.is_admin:
            raise HTTPException(403)
        username = str(form.get("username", "")).strip().lower()
        pw = str(form.get("password", ""))
        if not username or len(pw) < 8:
            flash(request, "Username and a password with at least 8 characters are required.", "error")
        elif db.scalar(select(User).where(User.username == username)):
            flash(request, "That username is taken.", "error")
        else:
            db.add(User(username=username, display_name=str(form.get("display_name", "")).strip(),
                        password_hash=hash_password(pw), is_admin=bool(form.get("is_admin"))))
            db.commit()
            flash(request, f"Added {username}.")
    return go("/settings")


@app.post("/settings/users/{uid}/delete")
async def settings_user_delete(request: Request, uid: int):
    await read_form(request)
    with db_session() as db:
        user = current_user(request, db)
        if not user.is_admin or uid == user.id:
            raise HTTPException(403)
        u = db.get(User, uid)
        if u:
            db.delete(u)
            db.commit()
    return go("/settings")


@app.get("/export.json")
def export_json(request: Request):
    """Download all recipes, cookbooks and the cooking log as JSON (backup / migration)."""
    with db_session() as db:
        current_user(request, db)
        recipes = db.scalars(select(Recipe).order_by(Recipe.id)).all()
        out = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "recipes": [{
                "id": r.id, "title": r.title, "description": r.description, "servings": r.servings,
                "prep_minutes": r.prep_minutes, "cook_minutes": r.cook_minutes,
                "ingredients": ing.lines(r.ingredients), "instructions": r.steps, "notes": r.notes,
                "tags": r.tag_list, "source_url": r.source_url, "image": r.image, "rating": r.rating,
                "favorite": r.favorite, "cookbooks": [c.name for c in r.cookbooks],
                "kind": r.kind, "bread": bread.load(r.bread) if r.kind == "bread" else None,
            } for r in recipes],
            "cookbooks": [{"name": b.name, "description": b.description, "color": b.color}
                          for b in db.scalars(select(Cookbook))],
            "cook_log": [{"date": l.cooked_on.isoformat(), "recipe_id": l.recipe_id, "title": l.label,
                          "guests": l.guests, "notes": l.notes, "rating": l.rating}
                         for l in db.scalars(select(CookLog).order_by(CookLog.cooked_on))],
        }
        return Response(json.dumps(out, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": "attachment; filename=cookbook-export.json"})


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    msgs = {404: "That page doesn't exist.", 403: "You don't have permission to do that."}
    msg = exc.detail if isinstance(exc.detail, str) and exc.detail not in ("Not Found", "Forbidden") \
        else msgs.get(exc.status_code, "Something went wrong.")
    return render(request, "error.html", {"code": exc.status_code, "message": msg}, status=exc.status_code)



# ---------------------------------------------------------------- display modes, cook mode, kitchen display

@app.get("/display/{mode}")
def set_display(request: Request, mode: str, next: str = "/"):
    if mode not in DISPLAY_MODES:
        raise HTTPException(404)
    if not next.startswith("/") or next.startswith("//"):
        next = "/"
    resp = go(next)
    resp.set_cookie("cookbook_display", mode, max_age=60 * 60 * 24 * 365 * 5, samesite="lax",
                    secure=config.SECURE_COOKIES)
    return resp


@app.get("/recipes/{rid}/cook", response_class=HTMLResponse)
def cook_mode(request: Request, rid: int, step: int = 0, servings: int | None = None,
              piece_weight: float | None = None, total: float | None = None, view: str = ""):
    """Step-by-step view: step 0 = ingredients, 1..n = method steps. Works without JavaScript (paged links),
    which is what e-paper readers need; tablets get swipe/arrow keys and a screen wake lock via app.js."""
    with db_session() as db:
        user = current_user(request, db)
        r = recipe_or_404(db, rid)
        factor = servings / r.servings if servings and r.servings else 1.0
        res = None
        if r.kind == "bread":
            res = bread_result(r, servings, piece_weight, total)
            lines = ing.lines(bread.ingredients_text(res))
        else:
            lines = [ing.scale_line(l, factor) for l in ing.lines(r.ingredients)]
        steps = [s for s in r.steps if not ing.is_header(s)]
        step = max(0, min(step, len(steps)))
        # Section header that applies to the current step, if any.
        section = ""
        n = 0
        for s in r.steps:
            if ing.is_header(s):
                section = ing.header_text(s)
            else:
                n += 1
                if n == step:
                    break
        # E-paper shows the whole recipe on one page by default (columns follow the screen size);
        # view=steps gives the one-step-per-screen mode, view=page the whole recipe in any mode.
        mode = display_mode(request)
        if view not in ("page", "steps"):
            view = "page" if mode == "epaper" else "steps"
        q = f"&servings={servings}" if servings else ""
        if res and piece_weight:
            q += f"&piece_weight={piece_weight:g}"
        if res and total:
            q += f"&total={total:g}"
        qb = q  # size only; the view links add their own view
        if mode == "epaper":
            q += "&view=steps"
        return render(request, "cook.html", {
            "r": r, "lines": lines, "steps": steps, "step": step, "total": len(steps),
            "section": section if step else "", "servings": servings or r.servings, "q": q, "res": res,
            "hide_nav": True, "view": view, "all_steps": r.steps, "qb": qb}, user=user)


def kiosk_allowed(request: Request, db, token: str) -> bool:
    if request.session.get("uid") and db.get(User, request.session["uid"]):
        return True
    saved = get_setting(db, "kiosk_token")
    return bool(saved and token and secrets.compare_digest(saved, token))


@app.get("/kitchen", response_class=HTMLResponse)
def kitchen_display(request: Request, token: str = "", refresh: int = 900, days: int = 3):
    """Read-only overview for a wall tablet or e-paper screen: today's and the next days' meals and the
    shopping list. Opens with a secret display link (no login needed) or when signed in."""
    with db_session() as db:
        if not kiosk_allowed(request, db, token):
            if not token:
                current_user(request, db)  # redirects to login
            raise HTTPException(403, "This display link is not valid any more. Create a new one in Settings.")
        today = date.today()
        mode = request.query_params.get("display") or display_mode(request)
        if "days" not in request.query_params and mode == "epaper":
            days = 7  # e-paper: CSS shows as many days as the screen has room for
        days = max(1, min(days, 7))
        plan = db.scalars(select(MealPlan).where(MealPlan.day >= today, MealPlan.day < today + timedelta(days=days))
                          .order_by(MealPlan.day)).all()
        by_day = {today + timedelta(days=i): [] for i in range(days)}
        for e in sorted(plan, key=lambda p: MEALS.index(p.meal) if p.meal in MEALS else 9):
            by_day[e.day].append(e)
        items = db.scalars(select(ShoppingItem).where(ShoppingItem.checked.is_(False))
                           .order_by(ShoppingItem.position)).all()
        last = db.scalars(select(CookLog).order_by(CookLog.cooked_on.desc(), CookLog.id.desc())
                          .limit(6 if mode == "epaper" else 3)).all()
        # "Cooking today": the next uncooked recipe planned for today (dinner first), shown in full on
        # displays with room for it.
        todays = [e for e in by_day.get(today, []) if e.recipe and not e.cooked]
        todays.sort(key=lambda e: 0 if e.meal == "dinner" else 1)
        feature, feature_lines = None, []
        if todays:
            e = todays[0]
            feature = e
            if e.recipe.kind == "bread":
                feature_lines = ing.lines(bread.ingredients_text(bread_result(e.recipe, e.servings)))
            else:
                f = e.servings / e.recipe.servings if e.servings and e.recipe.servings else 1.0
                feature_lines = [ing.scale_line(l, f) for l in ing.lines(e.recipe.ingredients)]
        return render(request, "kitchen.html", {
            "feature": feature, "feature_lines": feature_lines,
            "by_day": by_day, "items": items, "last": last, "now": datetime.now(),
            "refresh": max(60, refresh) if refresh else 0, "token": token, "mode": mode,
            "signed_in": bool(request.session.get("uid"))})


@app.post("/settings/kiosk")
async def settings_kiosk(request: Request):
    form = await read_form(request)
    with db_session() as db:
        user = current_user(request, db)
        if not user.is_admin:
            raise HTTPException(403)
        if form.get("action") == "revoke":
            set_setting(db, "kiosk_token", "")
            flash(request, "Display link turned off.")
        else:
            set_setting(db, "kiosk_token", secrets.token_urlsafe(24))
            flash(request, "New display link created. Old links stop working.")
        db.commit()
    return go("/settings#display")



@app.get("/levain", response_class=HTMLResponse)
def levain_calculator(request: Request, target: float = 45, s: float = 1, w: float = 3, f: float = 5,
                      h: float = 100):
    """Stand-alone sourdough levain build calculator (target weight + feed ratio + starter hydration)."""
    with db_session() as db:
        user = current_user(request, db)
        b = bread.levain_build(target, s, w, f, h)
        return render(request, "levain.html", {"b": b, "target": target, "s": s, "w": w, "f": f, "h": h},
                      user=user)
