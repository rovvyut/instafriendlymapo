"""India-specific ingredients + cooking method for any dish in the food database.

How this stays free:

Recipes are generated once per dish by the LLM and then cached in MongoDB
(``db.recipes``, keyed by ``food_code``). The first user to open a dish pays one
LLM call; everybody after that is served from the database at no cost. With 858
dishes the whole catalogue costs at most 858 calls, ever — and in practice far
fewer, because only popular dishes get opened.

Accuracy note: these are model-generated home-cooking recipes, not tested ones.
They are a helpful starting point, not a culinary authority, and the API labels
them as such so the UI can say so too.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from importlib import import_module
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError

from mapo_data import FOOD_DF

logger = logging.getLogger(__name__)

MODEL = "openai/gpt-oss-20b"
RECIPE_SCHEMA_VERSION = 1


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

class Ingredient(BaseModel):
    name: str = Field(max_length=120)
    quantity: str = Field(max_length=60)


class Recipe(BaseModel):
    food_code: str
    dish_name: str
    cuisine_region: str
    veg_flag: str
    servings: int = Field(ge=1, le=12)
    prep_time_min: int = Field(ge=0, le=240)
    cook_time_min: int = Field(ge=0, le=480)
    ingredients: List[Ingredient] = Field(min_length=1, max_length=30)
    steps: List[str] = Field(min_length=1, max_length=20)
    tips: List[str] = Field(default_factory=list, max_length=5)
    # Always true for now; kept explicit so the UI can show a disclaimer and so
    # a hand-written recipe could be stored later without breaking clients.
    ai_generated: bool = True


# --------------------------------------------------------------------------
# Prompting
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an experienced Indian home cook writing recipes for an Indian audience.

Rules:
- Assume a normal Indian home kitchen: kadhai, pressure cooker, tawa, mixer grinder. No sous-vide, no oven unless the dish genuinely needs one.
- Use ingredients available in an ordinary Indian kirana store or sabzi mandi. Prefer Indian names with a short English gloss where useful, e.g. "jeera (cumin seeds)", "besan (gram flour)".
- Use Indian household measures alongside metric: katori, cup, tsp, tbsp, grams, ml.
- Respect the dietary flag exactly. If the dish is marked veg, use NO egg, meat or fish, and no gelatin. If marked egg, egg is allowed but no meat or fish.If non-veg is marked then you can use fish and other meats, except pork and beef.
- Keep steps practical and in order. 4 to 10 steps. Each step one or two sentences.
- Do not invent a different dish. Write the recipe for the dish name you are given.

Return ONLY valid JSON. No markdown, no code fences, no commentary before or after."""

USER_TEMPLATE = """Write a home-style Indian recipe for this dish.

Dish: {dish_name}
Cuisine region: {cuisine_region}
Dietary flag: {veg_flag}
Typical serving: {serving_unit} (about {serving_grams} g), roughly {energy} kcal per serving

Return ONLY this JSON shape:
{{
  "servings": 2,
  "prep_time_min": 10,
  "cook_time_min": 20,
  "ingredients": [{{"name": "besan (gram flour)", "quantity": "1 katori"}}],
  "steps": ["First step.", "Second step."],
  "tips": ["One short tip."]
}}"""


def _extract_json(text: str) -> dict:
    """Models sometimes wrap JSON in prose or code fences despite instructions."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def _lookup_food(food_code: str) -> Optional[dict]:
    rows = FOOD_DF[FOOD_DF["food_code"].astype(str) == str(food_code)]
    if rows.empty:
        return None
    return rows.iloc[0].to_dict()


def _generate(row: dict) -> Recipe:
    """Blocking Groq call; run this through run_in_threadpool."""
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured.")

    groq_module = import_module("groq")
    client = groq_module.Groq(api_key=api_key)

    veg_flag = str(row.get("veg_flag") or "veg").lower()
    prompt = USER_TEMPLATE.format(
        dish_name=row["food_name"],
        cuisine_region=row.get("cuisine_region") or "Pan-Indian",
        veg_flag=veg_flag,
        serving_unit=row.get("servings_unit") or "serving",
        serving_grams=int(float(row.get("serving_grams") or 100)),
        energy=int(float(row.get("serv_energy") or 0)),
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        max_tokens=900,
    )
    data = _extract_json(response.choices[0].message.content or "")

    return Recipe(
        food_code=str(row["food_code"]),
        dish_name=str(row["food_name"]).strip(),
        cuisine_region=str(row.get("cuisine_region") or "Pan-Indian"),
        veg_flag=veg_flag,
        servings=int(data.get("servings", 2)),
        prep_time_min=int(data.get("prep_time_min", 10)),
        cook_time_min=int(data.get("cook_time_min", 20)),
        ingredients=data.get("ingredients", []),
        steps=[str(x) for x in data.get("steps", [])],
        tips=[str(x) for x in data.get("tips", [])][:5],
    )


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

async def get_cached_recipe(db, food_code: str) -> Optional[dict]:
    doc = await db.recipes.find_one(
        {"food_code": str(food_code), "schema_version": RECIPE_SCHEMA_VERSION}
    )
    if not doc:
        return None
    doc.pop("_id", None)
    doc.pop("schema_version", None)
    doc.pop("model", None)
    doc.pop("created_at", None)
    return doc


async def store_recipe(db, recipe: Recipe) -> None:
    doc = recipe.model_dump()
    doc["schema_version"] = RECIPE_SCHEMA_VERSION
    doc["model"] = MODEL
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.recipes.update_one(
        {"food_code": recipe.food_code, "schema_version": RECIPE_SCHEMA_VERSION},
        {"$set": doc},
        upsert=True,
    )


def build_recipe(food_code: str) -> Recipe:
    """Blocking. Raises LookupError if the dish is not in the database."""
    row = _lookup_food(food_code)
    if row is None:
        raise LookupError(food_code)
    return _generate(row)


def food_exists(food_code: str) -> bool:
    return _lookup_food(food_code) is not None


async def ensure_indexes(db) -> None:
    await db.recipes.create_index(
        [("food_code", 1), ("schema_version", 1)], unique=True
    )
