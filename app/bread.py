"""Baker's percentage calculator for bread recipes.

Model (same as a typical bakery spreadsheet):
- All percentages are relative to the TOTAL flour (= 100 %), including the flour inside the levain.
- Flours: each flour's share of the total flour (should add up to 100 %).
- Other ingredients (water, salt, oil, ...): % of total flour.
- Levain: its total weight as % of total flour (e.g. 50 %), and its composition as % of the levain's own
  flour: flours (should add up to 100 %) plus other ingredients (e.g. water 100 % = 100 % hydration).
- Dough size: number of pieces x piece weight, or a target total dough weight.

Example (from Philipp's sheet, "Bread rolls"): 14 x 75 g = 1050 g, total 171 % -> flour 614.0 g;
levain 50 % = 307.0 g at 100 % hydration -> 153.5 g flour + 153.5 g water; final dough = recipe - levain.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

LIQUID_WORDS = ("water", "wasser", "milk", "milch", "beer", "bier", "juice", "saft")


def _f(v, default: float | None = 0.0) -> float | None:
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(str(v).replace(",", ".").replace("%", "").replace("g", "").strip())
    except ValueError:
        return default


def default_spec() -> dict:
    return {
        "flours": [
            {"name": "Bread flour", "pct": 90, "levain_pct": 100},
            {"name": "Whole wheat flour", "pct": 10, "levain_pct": 0},
        ],
        "others": [
            {"name": "Water", "pct": 70, "levain_pct": 100, "liquid": True},
            {"name": "Salt", "pct": 2, "levain_pct": 0, "liquid": False},
        ],
        "levain_pct": 20,
        "pieces": 2,
        "piece_weight": 900,
        "total_weight": None,
        "piece_name": "loaves",
        # Optional: build the levain from a sourdough starter with a feed ratio starter:water:flour.
        # When enabled, the levain's hydration (its liquid row) follows from the ratio and starter hydration.
        "levain_build": {"enabled": False, "starter": 1, "water": 3, "flour": 5,
                         "starter_hydration": 100, "extra_pct": 10},
    }


def load(text: str | None) -> dict:
    if not text:
        return default_spec()
    try:
        spec = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default_spec()
    base = default_spec()
    base.update({k: v for k, v in spec.items() if k in base})
    return base


def dump(spec: dict) -> str:
    return json.dumps(spec, ensure_ascii=False)


def from_form(form) -> dict:
    """Read the bread editor fields (parallel lists, empty rows ignored)."""
    flours = []
    for name, pct, lpct in zip(form.getlist("flour_name"), form.getlist("flour_pct"), form.getlist("flour_lpct")):
        if str(name).strip():
            flours.append({"name": str(name).strip()[:80], "pct": _f(pct), "levain_pct": _f(lpct)})
    liquid_idx = {str(x) for x in form.getlist("other_liquid")}
    others = []
    for i, (name, pct, lpct) in enumerate(zip(form.getlist("other_name"), form.getlist("other_pct"),
                                              form.getlist("other_lpct"))):
        if str(name).strip():
            others.append({"name": str(name).strip()[:80], "pct": _f(pct), "levain_pct": _f(lpct),
                           "liquid": str(i) in liquid_idx})
    return {
        "flours": flours,
        "others": others,
        "levain_pct": _f(form.get("levain_pct")),
        "pieces": max(1, int(_f(form.get("pieces"), 1) or 1)),
        "piece_weight": _f(form.get("piece_weight"), None),
        "total_weight": _f(form.get("total_weight"), None),
        "piece_name": str(form.get("piece_name") or "pieces").strip()[:30],
        "levain_build": {
            "enabled": bool(form.get("build_enabled")),
            "starter": _f(form.get("build_starter"), 1), "water": _f(form.get("build_water"), 3),
            "flour": _f(form.get("build_flour"), 5),
            "starter_hydration": _f(form.get("build_starter_hydration"), 100),
            "extra_pct": _f(form.get("build_extra_pct"), 0),
        },
    }


@dataclass
class Row:
    name: str
    pct: float          # % of total flour (recipe column)
    weight: float       # recipe weight
    levain_pct: float   # % of levain flour
    levain_weight: float
    final_weight: float  # recipe - levain
    is_flour: bool = False
    liquid: bool = False


@dataclass
class Result:
    flour: Row
    flours: list[Row]
    others: list[Row]
    total_pct: float
    total_weight: float
    levain_pct: float
    levain_weight: float
    levain_flour_pct: float      # levain flour as % of total flour
    levain_hydration: float      # liquid in levain as % of levain flour
    hydration: float             # total liquid as % of total flour
    pieces: int
    piece_weight: float
    piece_name: str
    warnings: list[str] = field(default_factory=list)
    build: "LevainBuild | None" = None
    build_extra_pct: float = 0.0

    @property
    def final_total(self) -> float:
        return self.total_weight - self.levain_weight


def compute(spec: dict, pieces: int | None = None, piece_weight: float | None = None,
            total_weight: float | None = None) -> Result:
    flours = spec.get("flours") or []
    others = spec.get("others") or []
    pieces = int(pieces or spec.get("pieces") or 1)
    piece_weight = piece_weight if piece_weight is not None else spec.get("piece_weight")
    target = total_weight if total_weight is not None else spec.get("total_weight")
    warnings: list[str] = []

    if total_weight is not None:      # explicit override (e.g. from the recipe page)
        total = float(total_weight)
    elif target:                        # recipe saved with a target dough weight
        total = float(target)
    else:                               # pieces x piece weight
        total = float(pieces) * float(piece_weight or 0)
    piece_w = total / pieces if pieces else total

    flour_pct_sum = sum(_f(x.get("pct")) or 0 for x in flours)
    if flours and abs(flour_pct_sum - 100) > 0.05:
        warnings.append(f"The flours add up to {flour_pct_sum:g} %, not 100 %.")
    other_pct_sum = sum(_f(x.get("pct")) or 0 for x in others)
    total_pct = 100 + other_pct_sum
    flour_w = total * 100 / total_pct if total_pct else 0.0

    levain_pct = _f(spec.get("levain_pct")) or 0.0
    bset = build_settings(spec)
    if bset and levain_pct:
        # The feed ratio decides the levain's hydration: put it on the first liquid row, zero on other liquids.
        h = levain_build(100, bset.get("starter"), bset.get("water"), bset.get("flour"),
                         bset.get("starter_hydration")).hydration
        others = [dict(x) for x in others]
        first = next((x for x in others if x.get("liquid", any(w in str(x.get("name", "")).lower()
                                                                for w in LIQUID_WORDS))), None)
        for x in others:
            if x is first:
                x["levain_pct"] = round(h, 2)
            elif x.get("liquid", any(w in str(x.get("name", "")).lower() for w in LIQUID_WORDS)):
                x["levain_pct"] = 0
        if first is None:
            warnings.append("Add a water row so the levain's water can be counted.")
    levain_w = flour_w * levain_pct / 100
    lev_other_sum = sum(_f(x.get("levain_pct")) or 0 for x in others)
    levain_flour_w = levain_w * 100 / (100 + lev_other_sum) if levain_w else 0.0
    lev_flour_sum = sum(_f(x.get("levain_pct")) or 0 for x in flours)
    if levain_pct and flours and abs(lev_flour_sum - 100) > 0.05:
        warnings.append(f"The levain flours add up to {lev_flour_sum:g} %, not 100 %.")

    flour_rows = []
    for x in flours:
        pct = _f(x.get("pct")) or 0
        lpct = _f(x.get("levain_pct")) or 0
        w = flour_w * pct / 100
        lw = levain_flour_w * lpct / 100
        flour_rows.append(Row(x.get("name", ""), pct, w, lpct, lw, w - lw, is_flour=True))
    other_rows = []
    liquid = 0.0
    lev_liquid = 0.0
    for x in others:
        pct = _f(x.get("pct")) or 0
        lpct = _f(x.get("levain_pct")) or 0
        w = flour_w * pct / 100
        lw = levain_flour_w * lpct / 100
        is_liquid = bool(x.get("liquid", any(word in str(x.get("name", "")).lower() for word in LIQUID_WORDS)))
        if is_liquid:
            liquid += pct
            lev_liquid += lpct
        other_rows.append(Row(x.get("name", ""), pct, w, lpct, lw, w - lw, liquid=is_liquid))

    for r in flour_rows + other_rows:
        if r.final_weight < -0.05:
            warnings.append(f"The levain needs more {r.name} than the whole recipe has. "
                            f"Lower the levain or raise {r.name}.")
    flour_row = Row("Flour", 100.0, flour_w, 100.0 if levain_flour_w else 0.0, levain_flour_w,
                    flour_w - levain_flour_w, is_flour=True)
    build = None
    extra = 0.0
    if bset and levain_w:
        extra = _f(bset.get("extra_pct")) or 0.0
        build = levain_build(levain_w * (1 + extra / 100), bset.get("starter"), bset.get("water"),
                             bset.get("flour"), bset.get("starter_hydration"))
    return Result(
        build=build, build_extra_pct=extra,
        flour=flour_row, flours=flour_rows, others=other_rows, total_pct=total_pct, total_weight=total,
        levain_pct=levain_pct, levain_weight=levain_w,
        levain_flour_pct=levain_flour_w / flour_w * 100 if flour_w else 0.0,
        levain_hydration=lev_liquid, hydration=liquid, pieces=pieces, piece_weight=piece_w,
        piece_name=spec.get("piece_name") or "pieces", warnings=warnings,
    )


def g(w: float) -> str:
    """Grams with one decimal, like the sheet (e.g. 153.5 g)."""
    return f"{w:.1f}".rstrip("0").rstrip(".") if abs(w - round(w)) < 0.05 else f"{w:.1f}"


def ingredients_text(res: Result) -> str:
    """Plain ingredient lines (total recipe amounts) so search, shopping list and scaling keep working.
    The levain / final dough split is shown by the bread table on the recipe page."""
    lines = [f"{g(r.weight)} g {r.name}" for r in res.flours + res.others if r.weight > 0.05]
    return "\n".join(lines)


# ---------------------------------------------------------------- levain build (sourdough starter feed)

@dataclass
class LevainBuild:
    target: float            # levain weight to build (g)
    ratio: tuple[float, float, float]  # starter : water : flour
    starter_hydration: float  # % water per flour in the starter
    starter: float
    water: float
    flour: float
    starter_flour: float
    starter_water: float

    @property
    def parts(self) -> float:
        return sum(self.ratio)

    @property
    def total_flour(self) -> float:
        return self.flour + self.starter_flour

    @property
    def total_water(self) -> float:
        return self.water + self.starter_water

    @property
    def hydration(self) -> float:
        return self.total_water / self.total_flour * 100 if self.total_flour else 0.0


def levain_build(target: float, starter: float = 1, water: float = 3, flour: float = 5,
                 starter_hydration: float = 100) -> LevainBuild:
    """Split a target levain weight by a feed ratio (e.g. 1:3:5), accounting for the starter's own
    hydration. Example: 45 g at 1:3:5 -> 5 g starter, 15 g water, 25 g flour; with a 100 % starter the
    levain holds 27.5 g flour and 17.5 g water = 63.6 % hydration."""
    s, w, f = (max(0.0, _f(x) or 0.0) for x in (starter, water, flour))
    parts = s + w + f
    unit = (target or 0) / parts if parts else 0.0
    st = s * unit
    h = max(0.0, _f(starter_hydration, 100) or 0.0)
    st_flour = st * 100 / (100 + h)
    return LevainBuild(target=target or 0, ratio=(s, w, f), starter_hydration=h, starter=st,
                       water=w * unit, flour=f * unit, starter_flour=st_flour, starter_water=st - st_flour)


def build_settings(spec: dict) -> dict | None:
    b = spec.get("levain_build") or {}
    return b if b.get("enabled") else None
