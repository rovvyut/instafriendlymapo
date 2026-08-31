"""Nutrition math + personalised meal plan generator (ports user's original logic)."""
from importlib import import_module
import random
from typing import List, Optional, Annotated
from pydantic import BaseModel, Field

from mapo_data import FOOD_DF, veg_mask
import os
import json

groq_module = import_module("groq")

_groq_client = None


def _get_groq_client():
    """Built on first use, not at import time.

    Previously this ran ``os.environ["GROQ_API_KEY"]`` while the module was
    being imported, so a missing key raised KeyError and the entire API failed
    to start. Now only the one request that needs Groq fails.
    """
    global _groq_client
    if _groq_client is None:
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not configured.")
        _groq_client = groq_module.Groq(api_key=api_key)
    return _groq_client


class _LazyGroqClient:
    """Keeps the existing ``client.chat.completions.create(...)`` call sites working."""

    def __getattr__(self, item):
        return getattr(_get_groq_client(), item)


client = _LazyGroqClient()

try:
    load_dotenv = import_module("dotenv").load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        """Load environment variables when python-dotenv is available."""
        return False



# ---------------------------------------------------------------------------
# Original constants
# ---------------------------------------------------------------------------
ACTIVITY_MULTIPLIERS = {1: 1.2, 2: 1.375, 3: 1.55, 4: 1.725, 5: 1.9}
PROTEIN_MULTIPLIERS = {1: 1.2, 2: 2.0, 3: 2.0, 4: 2.2}
FAT_MULTIPLIERS = {1: 0.9, 2: 1.0, 3: 0.8, 4: 0.9}
CARB_MULTIPLIERS = {1: 2.0, 2: 2.5, 3: 3.0, 4: 4.0, 5: 5.0}

MEAL_SLOTS = ["early morning", "breakfast", "lunch", "high tea", "dinner"]
MEAL_CRITERIA = {"early morning": 0.01, "breakfast": 0.25, "lunch": 0.35, "high tea": 0.09, "dinner": 0.30}
EARLY_MORNING_OPTIONS = {"Lemon Ginger Water": "lemon ginger water",
                         "Cumin Infused Water": "cumin infused water"}
MIN_MULT, MAX_MULT = 0.5, 2.0


# ---------------------------------------------------------------------------
# Pure calculations (original formulas preserved)
# ---------------------------------------------------------------------------
def calculate_bmi(weight, height):
    bmi = round(weight / ((height / 100) ** 2), 2)
    if bmi < 18.5:
        insight = "Your BMI indicates that you are underweight."
    elif bmi < 25:
        insight = "Your BMI is within the healthy range."
    elif bmi < 30:
        insight = "Your BMI indicates that you are in the overweight category."
    elif bmi < 35:
        insight = "Your BMI falls within the obesity category (Class I)."
    elif bmi < 40:
        insight = "Your BMI indicates obesity (Class II)."
    else:
        insight = "Your BMI indicates severe obesity (Class III)."
    return bmi, insight


def calculate_bmr(weight, height, age, gender):
    if gender == "Male":
        BMR=round((10 * weight) + (6.25 * height) - (5 * age) + 5, 2)
        BMR_insight="BMR (Basal Metabolic Rate) is the estimated number of calories your body needs at complete rest to maintain essential functions like breathing, circulation, and body temperature. It represents your baseline energy requirement, not your daily calorie target. A higher BMR generally indicates greater energy needs at rest, while a lower BMR indicates lower resting energy needs."
    else:    
        BMR=round((10 * weight) + (6.25 * height) - (5 * age) - 161, 2)
        BMR_insight="BMR (Basal Metabolic Rate) is the estimated number of calories your body needs at complete rest to maintain essential functions like breathing, circulation, and body temperature. It represents your baseline energy requirement, not your daily calorie target. A higher BMR generally indicates greater energy needs at rest, while a lower BMR indicates lower resting energy needs. Your actual calorie requirement depends on your activity level and lifestyle, which are used to calculate TDEE."
    return BMR,BMR_insight


def calculate_tdee(activity_level,BMR):
    return round(BMR * ACTIVITY_MULTIPLIERS[activity_level], 2)


def goal_calling(goal, tdee, bmi):
    if goal == 1:
        return round(tdee, 0), "Your estimated calorie target maintains your current weight."
    if goal == 2:
        return round(tdee * 1.10, 0), "Your estimated calorie target supports gradual weight gain."
    if goal == 3:
        return round(tdee * 0.80, 0), "Your estimated calorie target supports gradual, sustainable fat loss."
    if goal == 4:
        m = 1.00 if bmi < 25 else 0.95 if bmi < 30 else 0.90 if bmi < 35 else 0.85
        return round(tdee * m, 0), "Your estimated calorie target supports body recomposition."
    return round(tdee, 0), "Maintaining current intake."


def calculate_macros(bmi, target_weight, weight, goal, activity_level):
    macro_weight = target_weight if bmi >= 25 else weight
    protein = round(macro_weight * PROTEIN_MULTIPLIERS[goal], 1)
    fat = round(macro_weight * FAT_MULTIPLIERS[goal], 1)
    carbs = round(macro_weight * CARB_MULTIPLIERS[activity_level], 1)
    return macro_weight, protein, fat, carbs


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
# Free-text entries are capped so they cannot be used to stuff an LLM prompt.
ShortText = Annotated[str, Field(max_length=80)]


class DietRequest(BaseModel):
    """Bounds matter here: `weight`/`height`/`age` feed BMI and BMR formulas, and
    the list fields drive one paid LLM call per unmatched favourite food, so an
    unbounded list is a billing DoS."""
    name: str = Field(default="Friend", max_length=100)
    weight: float = Field(gt=15, le=500)
    height: float = Field(gt=50, le=280)
    age: int = Field(ge=13, lt=120)
    gender: str = Field(default="Male", max_length=20)
    activity_level: int = Field(ge=1, le=5)
    goal: int = Field(ge=1, le=4)
    target_weight: float = Field(gt=15, le=500)
    meal_preference: str = Field(default="vegetarian", max_length=40)
    early_morning_choice: str = Field(default="Lemon Ginger Water", max_length=60)
    cuisines: List[ShortText] = Field(default_factory=list, max_length=20)
    dislikes: List[ShortText] = Field(default_factory=list, max_length=50)
    favourite_foods: List[ShortText] = Field(default_factory=list, max_length=10)


class FoodItem(BaseModel):
    name: str
    serving: str
    multiplier: float
    energy: float
    protein: float
    carbs: float
    fat: float


class MealOut(BaseModel):
    slot: str
    label: str
    target_calories: float
    foods: List[FoodItem]
    totals: dict


class NutritionInfo(BaseModel):
    name: str
    serving: str
    energy: float
    protein: float
    carbs: float
    fat: float
    source: str

class DietResponse(BaseModel):
    name: str
    bmi: float
    bmi_insight: str
    bmr: float
    tdee: float
    target_calories: float
    goal_insight: str
    macros: dict
    favourite_foods: List[NutritionInfo]
    meals: List[MealOut]
    daily_totals: dict

#Search Foods in database as well calling api
def find_food_in_database(food_name):
    query = food_name.strip()

    if not query:
        return None

    match = FOOD_DF[
        FOOD_DF["food_name"].str.contains(
            query,
            case=False,
            na=False,
            regex=False
        )
    ]

    if match.empty:
        return None

    r = match.iloc[0]

    return NutritionInfo(
        name=r["food_name"],
        serving=str(r["servings_unit"]),
        energy=round(float(r["serv_energy"]), 1),
        protein=round(float(r["serv_protein"]), 1),
        carbs=round(float(r["serv_carb"]), 1),
        fat=round(float(r["serv_fat"]), 1),
        source="MAPO Database"
    )

def get_food_from_api(food_name):
    prompt = f"""
    Provide nutritional information for this food:

    Food: {food_name}

    Give values for ONE standard serving.

    Return ONLY valid JSON in this format:
    {{
        "name": "{food_name}",
        "serving": "standard serving",
        "energy": 0,
        "protein": 0,
        "carbs": 0,
        "fat": 0
    }}

    Energy must be in kcal.
    Protein, carbs and fat must be in grams.
    """

    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "system",
                "content": """Act as a nutritionist.
            Provide nutritional information for ONE standard Indian serving.
            Return ONLY valid JSON.
            Do not include explanations, recipes, history, or any text outside the JSON.
            Do not exceed answer beyon 2-3 lines."""
    
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.5,
        max_completion_tokens=100
    )

    data = json.loads(response.choices[0].message.content)

    return NutritionInfo(
        name=data["name"],
        serving=data["serving"],
        energy=float(data["energy"]),
        protein=float(data["protein"]),
        carbs=float(data["carbs"]),
        fat=float(data["fat"]),
        source="Inhouse Food Database"
    )

def get_favourite_food_nutrition(favourite_foods):
    results = []

    for food in favourite_foods:
        db_result = find_food_in_database(food)

        if db_result:
            results.append(db_result)
        else:
            try:
                api_result = get_food_from_api(food)
                results.append(api_result)
            except Exception:
                results.append(
                    NutritionInfo(
                        name=food,
                        serving="Not available",
                        energy=0,
                        protein=0,
                        carbs=0,
                        fat=0,
                        source="Not Found"
                    )
                )

    return results

# ---------------------------------------------------------------------------
# Meal plan generator
# ---------------------------------------------------------------------------
def generate_diet_plan(req: DietRequest) -> DietResponse:

    Bmi = calculate_bmi(req.weight, req.height)
    BMR = calculate_bmr(req.weight, req.height, req.age, req.gender)
    
    tdee = calculate_tdee(req.activity_level, BMR)
    target_cal, goal_insight = goal_calling(req.goal, tdee, Bmi)

    favourite_foods = get_favourite_food_nutrition(
        req.favourite_foods
    )

    macro_weight, protein, fat, carbs = calculate_macros(
        Bmi,
        req.target_weight,
        req.weight,
        req.goal,
        req.activity_level
    )

    # rest of your existing code...





def _slot_pool(slot, meal_preference, cuisines, dislikes, food_types):
    df = FOOD_DF
    m = veg_mask(df, meal_preference) & df["meal_slots"].str.contains(slot, case=False, na=False)
    m &= df["food_type"].isin(food_types)
    if cuisines:
        m &= df["cuisine_region"].str.lower().isin([c.lower() for c in cuisines])
    pool = df[m]
    if dislikes:
        for d in dislikes:
            if d.strip():
                pool = pool[~pool["food_name"].str.contains(d.strip(), case=False, na=False)]
    if pool.empty:  # relax cuisine filter
        m = veg_mask(df, meal_preference) & df["meal_slots"].str.contains(slot, case=False, na=False)
        m &= df["food_type"].isin(food_types)
        pool = df[m]
    return pool


def _pick_foods(slot, budget, meal_preference, cuisines, dislikes, n_dishes, exclude=None):
    pool = _slot_pool(slot, meal_preference, cuisines, dislikes, ["dish"])
    if exclude:
        # Used by the weekly planner so a dish does not repeat across days.
        # If excluding everything would empty the slot, the exclusion is dropped
        # rather than returning a meal with no food in it.
        trimmed = pool[~pool["food_name"].isin(exclude)]
        if not trimmed.empty:
            pool = trimmed
    if pool.empty:
        return []
    n = min(n_dishes, len(pool))
    chosen = pool.sample(n)
    rows = chosen.to_dict("records")
    base_energy = sum(r["serv_energy"] for r in rows) or 1
    mult = max(MIN_MULT, min(MAX_MULT, round(budget / base_energy, 2)))
    items = []
    for r in rows:
        items.append(FoodItem(
            name=r["food_name"],
            serving=f"{mult}x {r['servings_unit']}",
            multiplier=mult,
            energy=round(r["serv_energy"] * mult, 1),
            protein=round(r["serv_protein"] * mult, 1),
            carbs=round(r["serv_carb"] * mult, 1),
            fat=round(r["serv_fat"] * mult, 1),
        ))
    return items


def _meal_totals(foods: List[FoodItem]):
    return {
        "energy": round(sum(f.energy for f in foods), 1),
        "protein": round(sum(f.protein for f in foods), 1),
        "carbs": round(sum(f.carbs for f in foods), 1),
        "fat": round(sum(f.fat for f in foods), 1),
    }


def generate_diet_plan(req: DietRequest) -> DietResponse:
    bmi, bmi_insight = calculate_bmi(req.weight, req.height)
    bmr = calculate_bmr(req.weight, req.height, req.age, req.gender)
    tdee = calculate_tdee(req.activity_level, bmr)
    target_cal, goal_insight = goal_calling(req.goal, tdee, bmi)
    macro_weight, protein, fat, carbs = calculate_macros(
        bmi, req.target_weight, req.weight, req.goal, req.activity_level)

    labels = {"early morning": "Early Morning", "breakfast": "Breakfast",
              "lunch": "Lunch", "high tea": "High Tea", "dinner": "Dinner"}
    dish_count = {"breakfast": 2, "lunch": 3, "high tea": 1, "dinner": 2}

    meals: List[MealOut] = []
    for slot in MEAL_SLOTS:
        budget = round(target_cal * MEAL_CRITERIA[slot], 0)
        if slot == "early morning":
            key = EARLY_MORNING_OPTIONS.get(req.early_morning_choice, "lemon ginger water")
            match = FOOD_DF[FOOD_DF["food_name"].str.contains(key, case=False, na=False)]
            foods = []
            if not match.empty:
                r = match.iloc[0]
                foods = [FoodItem(name=req.early_morning_choice, serving=f"1x {r['servings_unit']}",
                                  multiplier=1.0, energy=round(r["serv_energy"], 1),
                                  protein=round(r["serv_protein"], 1), carbs=round(r["serv_carb"], 1),
                                  fat=round(r["serv_fat"], 1))]
        else:
            foods = _pick_foods(slot, budget, req.meal_preference, req.cuisines,
                                req.dislikes, dish_count[slot])
        meals.append(MealOut(slot=slot, label=labels[slot], target_calories=budget,
                             foods=foods, totals=_meal_totals(foods)))
        favourite_foods = get_favourite_food_nutrition(
    req.favourite_foods
)
    daily = {
        "energy": round(sum(m.totals["energy"] for m in meals), 1),
        "protein": round(sum(m.totals["protein"] for m in meals), 1),
        "carbs": round(sum(m.totals["carbs"] for m in meals), 1),
        "fat": round(sum(m.totals["fat"] for m in meals), 1),
    }

   
    return DietResponse(
        name=req.name,
        bmi=bmi,
        bmi_insight=bmi_insight,
        bmr=bmr,
        tdee=tdee,
        target_calories=target_cal,
        goal_insight=goal_insight,
        macros={
            "protein": protein,
            "carbs": carbs,
            "fat": fat,
            "macro_weight": macro_weight
        },
        favourite_foods=favourite_foods,
        meals=meals,
        daily_totals=daily
    )

def swap_food(slot, target_energy, meal_preference, exclude, cuisines):
    """Return one alternative dish for a slot scaled to ~target_energy kcal."""
    pool = _slot_pool(slot, meal_preference, cuisines, [], ["dish"])
    if exclude:
        pool = pool[~pool["food_name"].isin(exclude)]
    if pool.empty:
        pool = _slot_pool(slot, meal_preference, [], [], ["dish"])
    if pool.empty:
        return None
    r = pool.sample(1).iloc[0]
    base = r["serv_energy"] or 1
    mult = max(MIN_MULT, min(MAX_MULT, round((target_energy or base) / base, 2)))
    return FoodItem(
        name=r["food_name"], serving=f"{mult}x {r['servings_unit']}", multiplier=mult,
        energy=round(r["serv_energy"] * mult, 1), protein=round(r["serv_protein"] * mult, 1),
        carbs=round(r["serv_carb"] * mult, 1), fat=round(r["serv_fat"] * mult, 1))


# ---------------------------------------------------------------------------
# Weekly plan — seven days, periodised into training and rest days
# ---------------------------------------------------------------------------
# The week is built on top of the daily generator, not beside it: the same
# BMI/BMR/TDEE/goal arithmetic runs once, and the seven days differ only in how
# the calorie budget is distributed and which dishes are drawn.
#
# Periodisation rule
# ------------------
# Protein and fat are held flat across the week — protein protects muscle in a
# deficit and fat runs the hormones, so neither is the lever. Carbohydrate is.
# A training day gets TRAINING_SHIFT more energy; the rest days give back
# exactly what the training days took, so the seven-day total still equals
# ``target_calories * 7``. With ``t`` training days and ``r = 7 - t`` rest days:
#
#     training = target * (1 + s)
#     rest     = target * (1 - s * t / r)
#
# which sums to ``target * 7`` for any split. A week that is all training or all
# rest has nothing to trade against, so the shift collapses to zero and every
# day sits on target.
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"]

TRAINING_SHIFT = 0.12   # training days run 12% above the daily target
CARB_FLOOR = 0.55       # a rest day never drops below 55% of baseline carbs


class WeeklyDietRequest(DietRequest):
    """A daily request plus which weekdays are training days (0 = Monday)."""
    training_days: List[int] = Field(default_factory=lambda: [0, 2, 4], max_length=7)
    vary_dishes: bool = True


class DayPlan(BaseModel):
    day_index: int
    weekday: str
    day_type: str
    target_calories: float
    macros: dict
    meals: List[MealOut]
    daily_totals: dict


class WeeklyDietResponse(BaseModel):
    name: str
    bmi: float
    bmi_insight: str
    bmr: float
    tdee: float
    base_target_calories: float
    goal_insight: str
    macros: dict
    training_days: List[int]
    training_shift: float
    week_target_calories: float
    days: List[DayPlan]
    week_totals: dict
    week_average: dict


def _day_targets(base_target: float, training_days: set) -> List[tuple]:
    """(day_type, calorie target) for each of the seven days.

    The rest-day reduction is derived from the training-day increase, so the
    week always sums back to ``base_target * 7``.
    """
    t = len(training_days)
    r = 7 - t
    shift = TRAINING_SHIFT if 0 < t < 7 else 0.0
    give_back = (shift * t / r) if r else 0.0
    out = []
    for i in range(7):
        if i in training_days:
            out.append(("training", round(base_target * (1 + shift), 0)))
        else:
            out.append(("rest", round(base_target * (1 - give_back), 0)))
    return out


def _day_macros(base_target, day_target, protein, fat, carbs):
    """Protein and fat are fixed; carbohydrate absorbs the day's calorie shift."""
    delta_kcal = day_target - base_target
    day_carbs = round(max(carbs * CARB_FLOOR, carbs + delta_kcal / 4.0), 1)
    return {"protein": protein, "fat": fat, "carbs": day_carbs,
            "carb_shift_g": round(day_carbs - carbs, 1)}


def generate_weekly_plan(req: WeeklyDietRequest) -> WeeklyDietResponse:
    bmi, bmi_insight = calculate_bmi(req.weight, req.height)
    bmr = calculate_bmr(req.weight, req.height, req.age, req.gender)
    tdee = calculate_tdee(req.activity_level, bmr)
    base_target, goal_insight = goal_calling(req.goal, tdee, bmi)
    macro_weight, protein, fat, carbs = calculate_macros(
        bmi, req.target_weight, req.weight, req.goal, req.activity_level)

    training = {d for d in req.training_days if 0 <= d <= 6}
    labels = {"early morning": "Early Morning", "breakfast": "Breakfast",
              "lunch": "Lunch", "high tea": "High Tea", "dinner": "Dinner"}
    dish_count = {"breakfast": 2, "lunch": 3, "high tea": 1, "dinner": 2}

    # One "already served" set per slot, so Monday's lunch does not reappear on
    # Thursday while breakfast is free to reuse a dish lunch happened to take.
    used = {slot: set() for slot in MEAL_SLOTS}

    days: List[DayPlan] = []
    for i, (day_type, day_target) in enumerate(_day_targets(base_target, training)):
        meals: List[MealOut] = []
        for slot in MEAL_SLOTS:
            budget = round(day_target * MEAL_CRITERIA[slot], 0)
            if slot == "early morning":
                key = EARLY_MORNING_OPTIONS.get(req.early_morning_choice,
                                                "lemon ginger water")
                match = FOOD_DF[FOOD_DF["food_name"].str.contains(key, case=False, na=False)]
                foods = []
                if not match.empty:
                    r = match.iloc[0]
                    foods = [FoodItem(name=req.early_morning_choice,
                                      serving=f"1x {r['servings_unit']}", multiplier=1.0,
                                      energy=round(r["serv_energy"], 1),
                                      protein=round(r["serv_protein"], 1),
                                      carbs=round(r["serv_carb"], 1),
                                      fat=round(r["serv_fat"], 1))]
            else:
                foods = _pick_foods(slot, budget, req.meal_preference, req.cuisines,
                                    req.dislikes, dish_count[slot],
                                    exclude=used[slot] if req.vary_dishes else None)
                if req.vary_dishes:
                    used[slot].update(f.name for f in foods)
            meals.append(MealOut(slot=slot, label=labels[slot], target_calories=budget,
                                 foods=foods, totals=_meal_totals(foods)))

        daily = {
            "energy": round(sum(m.totals["energy"] for m in meals), 1),
            "protein": round(sum(m.totals["protein"] for m in meals), 1),
            "carbs": round(sum(m.totals["carbs"] for m in meals), 1),
            "fat": round(sum(m.totals["fat"] for m in meals), 1),
        }
        days.append(DayPlan(
            day_index=i, weekday=WEEKDAYS[i], day_type=day_type,
            target_calories=day_target,
            macros=_day_macros(base_target, day_target, protein, fat, carbs),
            meals=meals, daily_totals=daily))

    week_totals = {k: round(sum(d.daily_totals[k] for d in days), 1)
                   for k in ("energy", "protein", "carbs", "fat")}
    week_average = {k: round(v / 7, 1) for k, v in week_totals.items()}

    return WeeklyDietResponse(
        name=req.name, bmi=bmi, bmi_insight=bmi_insight, bmr=bmr, tdee=tdee,
        base_target_calories=base_target, goal_insight=goal_insight,
        macros={"protein": protein, "carbs": carbs, "fat": fat,
                "macro_weight": macro_weight},
        training_days=sorted(training),
        training_shift=TRAINING_SHIFT if 0 < len(training) < 7 else 0.0,
        week_target_calories=round(base_target * 7, 0),
        days=days, week_totals=week_totals, week_average=week_average)
