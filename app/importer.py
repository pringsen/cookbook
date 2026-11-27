"""Import recipes from a web page (schema.org/Recipe, via recipe-scrapers with a JSON-LD fallback)."""
import html as htmllib
import json
import logging
import re
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36 SelfHostedCookbook/1.0"
)


@dataclass
class RecipeDraft:
    title: str = ""
    description: str = ""
    servings: int | None = None
    prep_minutes: int | None = None
    cook_minutes: int | None = None
    ingredients: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    notes: str = ""
    tags: list[str] = field(default_factory=list)
    source_url: str = ""
    image_url: str = ""

    def is_useful(self) -> bool:
        return bool(self.title and (self.ingredients or self.instructions))


class ImportError_(Exception):
    pass


def fetch(url: str) -> str:
    if not re.match(r"^https?://", url, re.I):
        raise ImportError_("Please enter a full link starting with http:// or https://")
    try:
        r = httpx.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en,de;q=0.8"},
                      follow_redirects=True, timeout=20)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ImportError_(f"Could not load the page: {e}") from e
    return r.text


def _int(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"\d+", str(v))
    return int(m.group()) if m else None


def _iso_minutes(v) -> int | None:
    """PT1H30M -> 90"""
    if not v:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?", str(v))
    if not m or not any(m.groups()):
        return _int(v)
    d, h, mi = (int(x) if x else 0 for x in m.groups())
    return d * 1440 + h * 60 + mi


def _text(s) -> str:
    s = htmllib.unescape(str(s or ""))
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _find_recipe_node(data):
    if isinstance(data, list):
        for d in data:
            r = _find_recipe_node(d)
            if r:
                return r
    elif isinstance(data, dict):
        t = data.get("@type")
        types = t if isinstance(t, list) else [t]
        if "Recipe" in types:
            return data
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in data:
                r = _find_recipe_node(data[key])
                if r:
                    return r
    return None


def _flatten_instructions(ins) -> list[str]:
    out: list[str] = []
    if isinstance(ins, str):
        parts = re.split(r"\n+|(?<=\.)\s{2,}", _text(ins) if "<" in ins else ins)
        return [p.strip() for p in parts if p.strip()]
    if isinstance(ins, dict):
        if ins.get("@type") == "HowToSection":
            if ins.get("name"):
                out.append(_text(ins["name"]) + ":")
            out += _flatten_instructions(ins.get("itemListElement", []))
        else:
            out.append(_text(ins.get("text") or ins.get("name")))
    elif isinstance(ins, list):
        for i in ins:
            out += _flatten_instructions(i)
    return [o for o in out if o]


def _image(v) -> str:
    if isinstance(v, list):
        v = v[0] if v else ""
    if isinstance(v, dict):
        v = v.get("url", "")
    return str(v or "")


def parse_jsonld(html: str, url: str) -> RecipeDraft | None:
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        node = _find_recipe_node(data)
        if not node:
            continue
        kw = node.get("keywords") or []
        if isinstance(kw, str):
            kw = kw.split(",")
        cats = node.get("recipeCategory") or []
        if isinstance(cats, str):
            cats = [cats]
        return RecipeDraft(
            title=_text(node.get("name")),
            description=_text(node.get("description")),
            servings=_int(node.get("recipeYield")[0] if isinstance(node.get("recipeYield"), list) else node.get("recipeYield")),
            prep_minutes=_iso_minutes(node.get("prepTime")),
            cook_minutes=_iso_minutes(node.get("cookTime")) or (
                None if node.get("prepTime") else _iso_minutes(node.get("totalTime"))),
            ingredients=[_text(i) for i in node.get("recipeIngredient") or node.get("ingredients") or [] if _text(i)],
            instructions=_flatten_instructions(node.get("recipeInstructions") or []),
            tags=[_text(t) for t in list(cats) + list(kw) if _text(t)][:12],
            source_url=url,
            image_url=_image(node.get("image")),
        )
    return None


def parse_with_scrapers(html: str, url: str) -> RecipeDraft | None:
    try:
        from recipe_scrapers import scrape_html
        s = scrape_html(html, org_url=url, supported_only=False)
    except Exception as e:  # unsupported site or no schema
        log.info("recipe-scrapers failed for %s: %s", url, e)
        return None

    def safe(fn, default=None):
        try:
            return fn()
        except Exception:
            return default

    groups = safe(s.ingredient_groups, None)
    ingredients: list[str] = []
    if groups and len(groups) > 1:
        for g in groups:
            if getattr(g, "purpose", None):
                ingredients.append(f"{g.purpose}:")
            ingredients += list(g.ingredients)
    else:
        ingredients = safe(s.ingredients, []) or []
    instructions = safe(s.instructions_list, None) or [
        x for x in (safe(s.instructions, "") or "").split("\n") if x.strip()]
    tags = []
    for fn in (s.category, s.keywords):
        v = safe(fn, None)
        if isinstance(v, str):
            tags += [t.strip() for t in v.split(",")]
        elif isinstance(v, list):
            tags += v
    d = RecipeDraft(
        title=safe(s.title, "") or "",
        description=safe(s.description, "") or "",
        servings=_int(safe(s.yields, None)),
        prep_minutes=_int(safe(s.prep_time, None)),
        cook_minutes=_int(safe(s.cook_time, None)),
        ingredients=[i for i in ingredients if i and i.strip()],
        instructions=[i.strip() for i in instructions if i and i.strip()],
        tags=[t for t in tags if t][:12],
        source_url=url,
        image_url=safe(s.image, "") or "",
    )
    if d.cook_minutes is None and d.prep_minutes is None:
        d.cook_minutes = _int(safe(s.total_time, None))
    return d if d.is_useful() else None


def page_text(html: str) -> str:
    """Visible text of a page, for the AI fallback."""
    html = re.sub(r"<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", html, flags=re.I)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:60000]


def import_url(url: str) -> tuple[RecipeDraft | None, str]:
    """Returns (draft or None, raw html)."""
    html = fetch(url)
    draft = parse_with_scrapers(html, url) or parse_jsonld(html, url)
    return draft, html


def download_image(url: str) -> bytes | None:
    if not url:
        return None
    try:
        r = httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20)
        r.raise_for_status()
        if len(r.content) > 15 * 1024 * 1024:
            return None
        return r.content
    except httpx.HTTPError:
        return None
