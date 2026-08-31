"""Ingredient-level nutrition for the two food experiences (burger, pizza).

Why this file exists
--------------------
``data/food_database.csv`` is a dish-level table: it knows what a
"Vegetable burger" costs you, but it has no row for a sesame bun or a slice of
cheddar. The burger anatomy and the pizza builder need to price a dish one
layer at a time, so the layer values have to come from somewhere real.

The rule here is: **the CSV wins whenever it has the row.** Every component
declares an optional ``db_name``; on import we look that name up in ``FOOD_DF``
and use its per-100 g macros. Only components the CSV genuinely does not carry
fall back to the reference constants below, which are per-100 g figures from
IFCT 2017 (Indian Food Composition Tables) and, for the non-Indian items,
USDA FoodData Central. Each fallback records its source so the provenance of a
number is never a mystery.

Macros are stored per 100 g and multiplied by the component's gram weight, the
same arithmetic ``mapo_data`` already applies to servings. Nothing is rounded
until it leaves the module, so removing and re-adding an ingredient returns to
exactly the number you started from.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from mapo_data import FOOD_DF

# --------------------------------------------------------------------------
# Per-100 g reference values for components the dish-level CSV does not carry.
# (kcal, protein g, carb g, fat g, fibre g)
# --------------------------------------------------------------------------
REFERENCE_PER_100G: Dict[str, dict] = {
    # --- burger ---------------------------------------------------------
    "sesame_bun":      {"kcal": 279.0, "protein": 9.0,  "carb": 50.0, "fat": 4.5,  "fibre": 2.2, "src": "USDA FDC 18350"},
    "whole_wheat_bun": {"kcal": 252.0, "protein": 10.2, "carb": 43.6, "fat": 3.9,  "fibre": 6.3, "src": "USDA FDC 18345"},
    "chicken_patty":   {"kcal": 195.0, "protein": 24.8, "carb": 1.4,  "fat": 10.1, "fibre": 0.0, "src": "IFCT 2017 (grilled chicken, minced)"},
    "veg_patty":       {"kcal": 168.0, "protein": 4.6,  "carb": 22.4, "fat": 6.9,  "fibre": 3.1, "src": "IFCT 2017 (aloo-matar tikki)"},
    "paneer_patty":    {"kcal": 265.0, "protein": 18.3, "carb": 4.1,  "fat": 20.2, "fibre": 0.4, "src": "IFCT 2017 (paneer, cow milk)"},
    "cheddar_slice":   {"kcal": 403.0, "protein": 24.9, "carb": 1.3,  "fat": 33.1, "fibre": 0.0, "src": "USDA FDC 1009"},
    "lettuce":         {"kcal": 15.0,  "protein": 1.4,  "carb": 2.2,  "fat": 0.2,  "fibre": 1.3, "src": "USDA FDC 11252"},
    "tomato_slice":    {"kcal": 18.0,  "protein": 0.9,  "carb": 3.9,  "fat": 0.2,  "fibre": 1.2, "src": "IFCT 2017 (tomato, ripe)"},
    "onion_ring":      {"kcal": 40.0,  "protein": 1.1,  "carb": 9.3,  "fat": 0.1,  "fibre": 1.7, "src": "IFCT 2017 (onion, big)"},

    # --- pizza ----------------------------------------------------------
    "pizza_base":      {"kcal": 270.0, "protein": 8.2,  "carb": 51.0, "fat": 3.5,  "fibre": 2.3, "src": "USDA FDC 18435"},
    "thin_base":       {"kcal": 288.0, "protein": 9.1,  "carb": 48.6, "fat": 6.2,  "fibre": 2.0, "src": "USDA FDC 18436"},
    "pizza_sauce":     {"kcal": 58.0,  "protein": 1.8,  "carb": 9.1,  "fat": 1.6,  "fibre": 1.9, "src": "USDA FDC 11695"},
    "mozzarella":      {"kcal": 300.0, "protein": 22.2, "carb": 2.2,  "fat": 22.4, "fibre": 0.0, "src": "USDA FDC 1026"},
    "paneer_topping":  {"kcal": 265.0, "protein": 18.3, "carb": 4.1,  "fat": 20.2, "fibre": 0.4, "src": "IFCT 2017 (paneer, cow milk)"},
    "chicken_tikka":   {"kcal": 172.0, "protein": 25.6, "carb": 3.2,  "fat": 6.4,  "fibre": 0.3, "src": "IFCT 2017 (tandoori chicken)"},
    "capsicum":        {"kcal": 24.0,  "protein": 1.2,  "carb": 4.4,  "fat": 0.3,  "fibre": 1.7, "src": "IFCT 2017 (capsicum, green)"},
    "mushroom":        {"kcal": 26.0,  "protein": 3.1,  "carb": 3.3,  "fat": 0.3,  "fibre": 1.0, "src": "IFCT 2017 (mushroom, button)"},
    "sweet_corn":      {"kcal": 96.0,  "protein": 3.4,  "carb": 21.0, "fat": 1.5,  "fibre": 2.7, "src": "IFCT 2017 (maize, sweet)"},
    "black_olive":     {"kcal": 115.0, "protein": 0.8,  "carb": 6.3,  "fat": 10.9, "fibre": 3.2, "src": "USDA FDC 9195"},
    "jalapeno":        {"kcal": 29.0,  "protein": 0.9,  "carb": 6.5,  "fat": 0.4,  "fibre": 2.8, "src": "USDA FDC 11979"},
}


def _from_db(db_name: str) -> Optional[dict]:
    """Per-100 g macros for a dish-level row, or None when the CSV lacks it."""
    if not db_name:
        return None
    match = FOOD_DF[FOOD_DF["food_name"].str.strip().str.lower() == db_name.strip().lower()]
    if match.empty:
        return None
    row = match.iloc[0]
    return {
        "kcal": float(row["energy_kcal"] or 0),
        "protein": float(row["protein_g"] or 0),
        "carb": float(row["carb_g"] or 0),
        "fat": float(row["fat_g"] or 0),
        "fibre": float(row["fibre_g"] or 0),
        "src": "MAPO food database",
    }


def _component(
    key: str,
    label: str,
    grams: float,
    *,
    ref: str = None,
    db_name: str = "",
    macro: str = "carb",
    removable: bool = True,
    max_count: int = 1,
    note: str = "",
) -> dict:
    """One layer of a dish, priced at its gram weight.

    ``macro`` is the macro this layer is *about* — what the label says it
    contributes — and drives which figure the UI leads with. It is a
    presentation hint only; the arithmetic always carries all four.
    """
    per100 = _from_db(db_name) or REFERENCE_PER_100G[ref or key]
    f = grams / 100.0
    return {
        "key": key,
        "label": label,
        "grams": grams,
        "macro": macro,
        "removable": removable,
        "max_count": max_count,
        "note": note,
        "source": per100["src"],
        "kcal": round(per100["kcal"] * f, 1),
        "protein": round(per100["protein"] * f, 1),
        "carbs": round(per100["carb"] * f, 1),
        "fat": round(per100["fat"] * f, 1),
        "fibre": round(per100["fibre"] * f, 1),
    }


def _burger() -> dict:
    return {
        "key": "burger",
        "name": "Burger",
        "mode": "deconstruct",
        "headline": "What's inside it?",
        # Ordered bottom-to-top, the way the thing is actually stacked.
        "layers": [
            _component("bun", "Bun", 55, ref="sesame_bun", macro="carbs",
                       removable=False, note="Sesame bun, crown and heel"),
            _component("patty", "Patty", 80, ref="chicken_patty", macro="protein",
                       max_count=2, note="Grilled chicken patty"),
            _component("cheese", "Cheese", 20, ref="cheddar_slice", macro="fat",
                       max_count=2, note="Cheddar slice"),
            # Split three ways rather than lumped as "vegetables": a tomato
            # slice and a ring of onion are not the same food, and the exploded
            # view shows them as separate layers, so they are priced separately.
            _component("lettuce", "Lettuce", 20, ref="lettuce", macro="fibre"),
            _component("onion", "Onion", 12, ref="onion_ring", macro="fibre"),
            _component("tomato", "Tomato", 25, ref="tomato_slice", macro="fibre"),
            _component("sauce", "Sauce", 22, db_name="Mayonnaise", macro="fat",
                       note="Mayonnaise"),
        ],
        # Swappable pieces, so "change the food, see the consequence" is real.
        "variants": {
            "bun": [
                {"key": "sesame_bun", "label": "Sesame", "grams": 55},
                {"key": "whole_wheat_bun", "label": "Whole wheat", "grams": 55},
            ],
            "patty": [
                {"key": "chicken_patty", "label": "Chicken", "grams": 80},
                {"key": "veg_patty", "label": "Veg", "grams": 80},
                {"key": "paneer_patty", "label": "Paneer", "grams": 80},
            ],
            "sauce": [
                {"key": "Mayonnaise", "label": "Mayo", "grams": 22, "db": True},
                {"key": "Tomato ketchup", "label": "Ketchup", "grams": 22, "db": True},
                {"key": "Cheese sauce", "label": "Cheese sauce", "grams": 22, "db": True},
            ],
        },
    }


def _pizza() -> dict:
    return {
        "key": "pizza",
        "name": "Pizza",
        "mode": "construct",
        "headline": "Build it and watch it cost you.",
        "layers": [
            _component("base", "Base", 120, ref="pizza_base", macro="carbs",
                       removable=False, note="9-inch hand-tossed base"),
            _component("sauce", "Sauce", 60, ref="pizza_sauce", macro="carbs",
                       note="Tomato pizza sauce"),
            _component("cheese", "Cheese", 60, ref="mozzarella", macro="fat",
                       max_count=2, note="Mozzarella"),
        ],
        "toppings": [
            _component("paneer", "Paneer", 40, ref="paneer_topping", macro="protein"),
            _component("chicken", "Chicken tikka", 40, ref="chicken_tikka", macro="protein"),
            _component("capsicum", "Capsicum", 25, ref="capsicum", macro="fibre"),
            _component("mushroom", "Mushroom", 25, ref="mushroom", macro="fibre"),
            _component("corn", "Sweet corn", 30, ref="sweet_corn", macro="carbs"),
            _component("olive", "Black olives", 15, ref="black_olive", macro="fat"),
            _component("jalapeno", "Jalapeño", 12, ref="jalapeno", macro="fibre"),
        ],
        "variants": {
            "base": [
                {"key": "pizza_base", "label": "Hand tossed", "grams": 120},
                {"key": "thin_base", "label": "Thin crust", "grams": 85},
            ],
        },
        # Size acts as a multiplier on every gram weight in the dish.
        "sizes": [
            {"key": "regular", "label": "Regular 7\"", "factor": 0.62},
            {"key": "medium", "label": "Medium 9\"", "factor": 1.0},
            {"key": "large", "label": "Large 12\"", "factor": 1.72},
        ],
    }


def resolve_variant(ref_or_db: str, grams: float, from_db: bool = False) -> dict:
    """Price one swappable piece. Used by the client when a variant changes."""
    per100 = _from_db(ref_or_db) if from_db else REFERENCE_PER_100G.get(ref_or_db)
    if per100 is None:
        per100 = _from_db(ref_or_db) or REFERENCE_PER_100G.get(ref_or_db)
    if per100 is None:
        raise KeyError(ref_or_db)
    f = grams / 100.0
    return {
        "kcal": round(per100["kcal"] * f, 1),
        "protein": round(per100["protein"] * f, 1),
        "carbs": round(per100["carb"] * f, 1),
        "fat": round(per100["fat"] * f, 1),
        "fibre": round(per100["fibre"] * f, 1),
        "source": per100["src"],
    }


def build_components() -> dict:
    """Everything the burger and pizza experiences need, priced once."""
    burger = _burger()
    pizza = _pizza()

    # Pre-price every variant so the client never has to do nutrition maths.
    for dish in (burger, pizza):
        priced = {}
        for slot, options in dish.get("variants", {}).items():
            priced[slot] = [
                {
                    **opt,
                    **resolve_variant(opt["key"], opt["grams"], from_db=opt.get("db", False)),
                }
                for opt in options
            ]
        dish["variants"] = priced

    return {"dishes": {"burger": burger, "pizza": pizza}}


COMPONENTS = build_components()


def get_dish(key: str) -> Optional[dict]:
    return COMPONENTS["dishes"].get(key)


def list_dishes() -> List[str]:
    return list(COMPONENTS["dishes"].keys())
