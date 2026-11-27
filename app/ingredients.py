"""Small, forgiving ingredient-line parser used for scaling and the shopping list.

"1 1/2 cups flour, sifted" -> (1.5, "cup", "flour", "sifted")
"200 g Mehl"               -> (200, "g", "Mehl", "")
"Salt to taste"            -> (None, "", "Salt to taste", "")
"""
import re
from dataclasses import dataclass
from fractions import Fraction

UNICODE_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅕": "1/5",
    "⅖": "2/5", "⅗": "3/5", "⅘": "4/5", "⅙": "1/6", "⅚": "5/6", "⅛": "1/8",
    "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
}

# alias -> canonical unit
UNITS = {
    # metric
    "g": "g", "gr": "g", "gram": "g", "grams": "g", "gramm": "g",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg", "kilo": "kg",
    "mg": "mg",
    "ml": "ml", "milliliter": "ml", "millilitre": "ml", "milliliters": "ml",
    "cl": "cl", "dl": "dl",
    "l": "l", "liter": "l", "litre": "l", "liters": "l", "litres": "l",
    # imperial / US
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp", "t": "tsp",
    "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp", "tbs": "tbsp", "tbl": "tbsp",
    "cup": "cup", "cups": "cup", "c": "cup",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "pint": "pint", "pints": "pint", "quart": "quart", "quarts": "quart",
    "fl oz": "fl oz",
    # German
    "el": "tbsp", "essl": "tbsp", "esslöffel": "tbsp",
    "tl": "tsp", "teel": "tsp", "teelöffel": "tsp",
    "msp": "pinch", "prise": "pinch", "prisen": "pinch",
    "pck": "pkg", "pkg": "pkg", "päckchen": "pkg", "packung": "pkg", "pack": "pkg", "package": "pkg",
    "stk": "pc", "stück": "pc", "st": "pc", "pc": "pc", "pcs": "pc", "piece": "pc", "pieces": "pc",
    "dose": "can", "dosen": "can", "can": "can", "cans": "can",
    "bund": "bunch", "bunch": "bunch", "bunches": "bunch",
    "zehe": "clove", "zehen": "clove", "clove": "clove", "cloves": "clove",
    "becher": "cup", "tasse": "cup", "tassen": "cup",
    "pinch": "pinch", "pinches": "pinch", "dash": "dash",
    "scheibe": "slice", "scheiben": "slice", "slice": "slice", "slices": "slice",
}

_NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?)"
_QTY_RE = re.compile(rf"^\s*(?P<q1>{_NUM})(?:\s*(?:-|–|to|bis)\s*(?P<q2>{_NUM}))?\s*(?P<rest>.*)$", re.I)


@dataclass
class Parsed:
    quantity: float | None
    unit: str
    name: str
    note: str

    def key(self) -> tuple[str, str]:
        return (normalize_name(self.name), self.unit)


def _to_float(s: str) -> float:
    s = s.replace(",", ".").strip()
    if " " in s:
        whole, frac = s.split(None, 1)
        return float(whole) + float(Fraction(frac))
    if "/" in s:
        return float(Fraction(s))
    return float(s)


def _clean(line: str) -> str:
    for k, v in UNICODE_FRACTIONS.items():
        # "1½" -> "1 1/2"
        line = re.sub(rf"(\d){k}", rf"\1 {v}", line)
        line = line.replace(k, v)
    line = re.sub(r"^\s*[-*•·]\s*", "", line)  # bullets
    return line.strip()


def is_header(line: str) -> bool:
    s = line.strip()
    return bool(s) and (s.endswith(":") or s.startswith("#"))


def header_text(line: str) -> str:
    return line.strip().lstrip("#").rstrip(":").strip()


def parse(line: str) -> Parsed:
    line = _clean(line)
    qty = None
    rest = line
    m = _QTY_RE.match(line)
    if m:
        try:
            qty = _to_float(m.group("q1"))
            if m.group("q2"):  # range -> use upper bound for shopping
                qty = _to_float(m.group("q2"))
            rest = m.group("rest")
        except (ValueError, ZeroDivisionError):
            qty, rest = None, line
    unit = ""
    if qty is not None:
        # "200g" glued, or "2 EL", "1 fl oz"
        um = re.match(r"^(fl\.?\s?oz|[A-Za-zÄÖÜäöüß]+)\.?\s*(?:of\s+)?(.*)$", rest)
        if um and um.group(1).lower().replace(".", "") in UNITS:
            unit = UNITS[um.group(1).lower().replace(".", "")]
            rest = um.group(2)
    note = ""
    if "," in rest:
        rest, note = [p.strip() for p in rest.split(",", 1)]
    pm = re.search(r"\(([^)]*)\)", rest)
    if pm:
        note = (pm.group(1) + (", " + note if note else "")).strip()
        rest = (rest[: pm.start()] + rest[pm.end():]).strip()
    return Parsed(qty, unit, rest.strip() or line, note)


def normalize_name(name: str) -> str:
    n = name.lower().strip()
    n = re.sub(r"\s+", " ", n)
    # crude plural folding so "onions" and "onion" merge
    if len(n) > 3 and n.endswith("es") and n[:-2].endswith(("o", "ch", "sh", "x")):
        n = n[:-2]
    elif len(n) > 3 and n.endswith("s") and not n.endswith("ss"):
        n = n[:-1]
    return n


def fmt_qty(q: float | None) -> str:
    if q is None:
        return ""
    if abs(q - round(q)) < 0.01:
        return str(int(round(q)))
    whole = int(q)
    frac = q - whole
    for den in (2, 3, 4, 8):
        num = round(frac * den)
        if num and abs(frac - num / den) < 0.02:
            f = Fraction(num, den)
            return f"{whole} {f}" if whole else f"{f}"
    return f"{q:.2f}".rstrip("0").rstrip(".")


def scale_line(line: str, factor: float) -> str:
    """Return the ingredient line with its quantity multiplied by factor."""
    if factor == 1 or is_header(line):
        return line
    cleaned = _clean(line)
    m = _QTY_RE.match(cleaned)
    if not m:
        return line
    try:
        q1 = _to_float(m.group("q1")) * factor
        q = fmt_qty(q1)
        if m.group("q2"):
            q += "–" + fmt_qty(_to_float(m.group("q2")) * factor)
    except (ValueError, ZeroDivisionError):
        return line
    rest = m.group("rest")
    return f"{q} {rest}".strip()


def lines(text: str) -> list[str]:
    return [l.rstrip() for l in (text or "").splitlines() if l.strip()]


# Units that are merged on the shopping list by converting to a base unit.
TO_BASE = {"kg": ("g", 1000), "mg": ("g", 0.001), "l": ("ml", 1000), "dl": ("ml", 100), "cl": ("ml", 10)}


def to_base(qty: float | None, unit: str) -> tuple[float | None, str]:
    if qty is not None and unit in TO_BASE:
        base, f = TO_BASE[unit]
        return qty * f, base
    return qty, unit


def display_amount(qty: float | None, unit: str) -> str:
    """'1500 g' -> '1.5 kg', '250 ml' stays."""
    if qty is not None and unit == "g" and qty >= 1000:
        qty, unit = qty / 1000, "kg"
    elif qty is not None and unit == "ml" and qty >= 1000:
        qty, unit = qty / 1000, "l"
    return " ".join(x for x in (fmt_qty(qty), unit) if x)
