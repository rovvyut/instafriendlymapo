#!/usr/bin/env python3
"""Wire the new guards into nutrition.py and server.py.

Run once, from the backend folder:

    cd backend && python3 patch_backend.py

It is idempotent — running it twice is safe, it just reports "already applied".
Every edit asserts on its anchor first, so if your files have drifted it stops
with a clear message instead of half-applying. A .bak of each file is written
before anything changes.

What it does
------------
nutrition.py
  1. find_food_in_database   -> ranked matching via food_lookup (no more
                                first-substring guesses like dal -> daliya)
  2. get_favourite_food_nutrition
                             -> raises UnknownFoodError instead of calling
                                Groq. Unrecognised input is reported, never
                                guessed and never billed.

server.py
  3. ai_coach import blocker  -> nothing to do here; that fix ships in the
                                 replacement ai_coach.py
  4. /diet/plan               -> runs in a threadpool so a slow request cannot
                                 stall the event loop for every other user
  5. /diet/plan               -> returns 422 with suggestions on unknown food
  6. /diet/plan               -> per-user daily cap, matching /coach and /recipe
"""
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).parent
CHANGES = []
SKIPPED = []


def backup(path):
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)


def replace_function(src, name, new_body):
    """Swap a whole top-level function, whatever its internal whitespace."""
    pattern = re.compile(
        r"^def " + re.escape(name) + r"\(.*?(?=^\S|\Z)",
        re.S | re.M,
    )
    if not pattern.search(src):
        return None
    return pattern.sub(new_body.rstrip() + "\n\n\n", src, count=1)


# ---------------------------------------------------------------- nutrition
def patch_nutrition():
    p = ROOT / "nutrition.py"
    if not p.exists():
        print("  ! nutrition.py not found"); return
    src = p.read_text(encoding="utf-8")

    if "food_lookup" in src:
        SKIPPED.append("nutrition.py (already patched)")
        return

    if "import food_lookup" not in src:
        anchor = "from mapo_data import FOOD_DF, veg_mask"
        assert anchor in src, "could not find the mapo_data import in nutrition.py"
        src = src.replace(
            anchor,
            anchor + "\nfrom food_lookup import (\n"
            "    UnknownFoodError,\n"
            "    resolve_favourites,\n"
            "    resolve as _resolve_food,\n"
            ")",
            1,
        )

    new_find = '''def find_food_in_database(food_name):
    """Ranked lookup, replacing the old first-substring match.

    That match returned confidently wrong foods — "dal" resolved to a sweet
    semolina porridge, "egg" to egg nog, "pav bhaji" to the spice powder —
    because it took whichever row happened to contain the string first. This
    scores exact names, bracketed local names and whole-word hits above loose
    substrings, and returns None rather than a bad guess.
    """
    row, _score = _resolve_food(food_name or "")
    if row is None:
        return None
    return NutritionInfo(
        name=row["food_name"],
        serving=str(row["servings_unit"]),
        energy=round(float(row["serv_energy"]), 1),
        protein=round(float(row["serv_protein"]), 1),
        carbs=round(float(row["serv_carb"]), 1),
        fat=round(float(row["serv_fat"]), 1),
        source="MAPO food database",
    )
'''
    out = replace_function(src, "find_food_in_database", new_find)
    assert out is not None, "find_food_in_database not found in nutrition.py"
    src = out

    new_fav = '''def get_favourite_food_nutrition(favourite_foods):
    """Resolve favourites from the database, or refuse.

    Previously an unmatched name fell through to a paid LLM call, and if that
    failed a zero-calorie "Not Found" row was silently added to the plan. Ten
    junk strings therefore meant ten billed calls, repeatable in a loop, from
    any account. Now nothing leaves the process: a name either matches the
    database or comes back to the user as a 422 with spelling suggestions.
    """
    if not favourite_foods:
        return []
    resolved = resolve_favourites(favourite_foods)   # raises UnknownFoodError
    return [
        NutritionInfo(
            name=r["name"],
            serving=r["serving"],
            energy=r["energy"],
            protein=r["protein"],
            carbs=r["carbs"],
            fat=r["fat"],
            source=r["source"],
        )
        for r in resolved
    ]
'''
    out = replace_function(src, "get_favourite_food_nutrition", new_fav)
    assert out is not None, "get_favourite_food_nutrition not found in nutrition.py"
    src = out

    backup(p)
    p.write_text(src, encoding="utf-8")
    CHANGES.append("nutrition.py: ranked food matching + no LLM fallback")


# ------------------------------------------------------------------- server
def patch_server():
    p = ROOT / "server.py"
    if not p.exists():
        print("  ! server.py not found"); return
    src = p.read_text(encoding="utf-8")

    if "UnknownFoodError" in src:
        SKIPPED.append("server.py (already patched)")
        return

    anchor = "from nutrition import ("
    assert anchor in src, "could not find the nutrition import block in server.py"
    src = src.replace(anchor, "from food_lookup import UnknownFoodError\n" + anchor, 1)

    old = '''@api.post("/diet/plan", response_model=DietResponse)
async def diet_plan(req: DietRequest, user: dict = Depends(get_current_user)):
    try:
        return generate_diet_plan(req)
    except Exception:'''
    assert old in src, "the /diet/plan handler does not look the way this patch expects"

    new = '''# Generating a plan is real work — pandas over the whole food table. It used to
# run inline in the event loop, so one request blocked every other user's.
# It is also the only endpoint that was uncapped, while /coach and /recipe both
# limit per user per day; that asymmetry is closed here.
DIET_PLAN_DAILY_LIMIT = int(os.environ.get("DIET_PLAN_DAILY_LIMIT", "40"))


async def _check_plan_quota(user_id: str) -> None:
    day = datetime.now(timezone.utc).date().isoformat()
    usage = await db.plan_usage.find_one({"user_id": user_id, "date": day})
    if (usage["count"] if usage else 0) >= DIET_PLAN_DAILY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="You have generated a lot of plans today. Try again tomorrow.",
        )
    await db.plan_usage.update_one(
        {"user_id": user_id, "date": day},
        {"$inc": {"count": 1}, "$setOnInsert": {"user_id": user_id, "date": day}},
        upsert=True,
    )


@api.post("/diet/plan", response_model=DietResponse)
async def diet_plan(req: DietRequest, user: dict = Depends(get_current_user)):
    await _check_plan_quota(user["id"])
    try:
        return await run_in_threadpool(generate_diet_plan, req)
    except UnknownFoodError as e:
        # A typo is the user's to fix, not something to guess at. 422 carries
        # which entries failed and what they might have meant.
        raise HTTPException(status_code=422, detail=e.as_detail())
    except HTTPException:
        raise
    except Exception:'''
    src = src.replace(old, new, 1)

    # the weekly endpoint should answer the same way
    old_week = '''    try:
        return await run_in_threadpool(generate_weekly_plan, req)
    except Exception:'''
    if old_week in src:
        src = src.replace(old_week, '''    await _check_plan_quota(user["id"])
    try:
        return await run_in_threadpool(generate_weekly_plan, req)
    except UnknownFoodError as e:
        raise HTTPException(status_code=422, detail=e.as_detail())
    except HTTPException:
        raise
    except Exception:''', 1)

    backup(p)
    p.write_text(src, encoding="utf-8")
    CHANGES.append("server.py: threadpool + 422 on unknown food + daily cap")


def main():
    print("Patching MAPO backend...\n")
    try:
        patch_nutrition()
        patch_server()
    except AssertionError as e:
        print(f"\n  STOPPED: {e}")
        print("  Nothing was half-applied. Restore any .bak files if needed.")
        return 1

    for c in CHANGES:
        print(f"  applied  {c}")
    for s in SKIPPED:
        print(f"  skipped  {s}")
    if CHANGES:
        print("\n  .bak files written next to each changed file.")
    print("\nNext:")
    print("  1. drop in the new ai_coach.py (fixes the foodu_chatbot import)")
    print("  2. python3 -c 'import server'      # must print nothing")
    print("  3. commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
