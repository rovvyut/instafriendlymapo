"""MAPO AI Nutrition Coach — user's original rule-based Hinglish chatbot (adapted)."""
import re
from typing import Dict, Any, List, Optional

from mapo_data import FOOD_DF, ALCOHOL_DF

BRAND_MAPPINGS = {
    "mimosa": {"base": "Mimosa", "std_ml": 120, "cal_per_30ml": 25},
    "mojito": {"base": "Mojito", "std_ml": 200, "cal_per_30ml": 22},
    "bloody mary": {"base": "Bloody Mary", "std_ml": 180, "cal_per_30ml": 20},
    "cosmopolitan": {"base": "Cosmopolitan", "std_ml": 100, "cal_per_30ml": 45},
    "mai tai": {"base": "Mai Tai", "std_ml": 150, "cal_per_30ml": 40},
    "rum and coke": {"base": "Rum and Coke", "std_ml": 200, "cal_per_30ml": 25},
    "white russian": {"base": "White Russian", "std_ml": 150, "cal_per_30ml": 50},
    "old fashioned": {"base": "Old Fashioned", "std_ml": 90, "cal_per_30ml": 55},
    "martini": {"base": "Martini", "std_ml": 90, "cal_per_30ml": 50},
    "long island iced tea": {"base": "LIIT", "std_ml": 220, "cal_per_30ml": 35},
    "liit": {"base": "LIIT", "std_ml": 220, "cal_per_30ml": 35},
    "pina colada": {"base": "Piña Colada", "std_ml": 200, "cal_per_30ml": 45},
    "beluga": {"base": "Vodka", "std_ml": 30, "cal_per_30ml": 65},
    "absolut": {"base": "Vodka", "std_ml": 30, "cal_per_30ml": 65},
    "smirnoff": {"base": "Vodka", "std_ml": 30, "cal_per_30ml": 65},
    "grey goose": {"base": "Vodka", "std_ml": 30, "cal_per_30ml": 65},
    "royal stag": {"base": "Whiskey", "std_ml": 30, "cal_per_30ml": 70},
    "blenders pride": {"base": "Whiskey", "std_ml": 30, "cal_per_30ml": 70},
    "johnnie walker": {"base": "Whiskey", "std_ml": 30, "cal_per_30ml": 70},
    "chivas regal": {"base": "Whiskey", "std_ml": 30, "cal_per_30ml": 70},
    "old monk": {"base": "Dark Rum", "std_ml": 30, "cal_per_30ml": 65},
    "bacardi": {"base": "Rum", "std_ml": 30, "cal_per_30ml": 65},
    "bombay sapphire": {"base": "Gin", "std_ml": 30, "cal_per_30ml": 65},
    "tanqueray": {"base": "Gin", "std_ml": 30, "cal_per_30ml": 65},
    "sula": {"base": "Wine", "std_ml": 150, "cal_per_30ml": 24},
    "chardonnay": {"base": "Wine", "std_ml": 150, "cal_per_30ml": 24},
    "kingfisher": {"base": "Beer", "std_ml": 330, "cal_per_30ml": 13},
    "bira": {"base": "Beer", "std_ml": 330, "cal_per_30ml": 13},
    "budweiser": {"base": "Beer", "std_ml": 330, "cal_per_30ml": 13},
    "heineken": {"base": "Beer", "std_ml": 330, "cal_per_30ml": 13},
    "corona": {"base": "Beer", "std_ml": 330, "cal_per_30ml": 13},
}

ACTIVITY_MULT = {1: 1.2, 2: 1.375, 3: 1.55, 4: 1.725, 5: 1.9}


def calculate_user_profile_targets(user_data: Dict[str, Any]) -> Dict[str, Any]:
    weight = float(user_data.get("weight", 70.0))
    height = float(user_data.get("height", 170.0))
    age = int(user_data.get("age", 25))
    gender = str(user_data.get("gender", "male")).lower()
    activity = int(user_data.get("activity_level", 2))
    goal = int(user_data.get("goal", 3))
    target_weight = float(user_data.get("target_weight", weight))

    bmi = round(weight / ((height / 100) ** 2), 2)
    if gender == "male":
        bmr = round((10 * weight) + (6.25 * height) - (5 * age) + 5, 2)
    else:
        bmr = round((10 * weight) + (6.25 * height) - (5 * age) - 161, 2)
    tdee = round(bmr * ACTIVITY_MULT.get(activity, 1.375), 2)

    if goal == 1:
        target_calories = tdee
    elif goal == 2:
        target_calories = tdee * 1.10
    elif goal == 3:
        target_calories = max(tdee * 0.80, 1500 if gender == "male" else 1200)
    elif goal == 4:
        target_calories = tdee * (1.0 if bmi < 25 else 0.95 if bmi < 30 else 0.90 if bmi < 35 else 0.85)
    else:
        target_calories = tdee

    return {"name": user_data.get("name", "User"), "bmi": bmi, "bmr": bmr, "tdee": tdee,
            "target_calories": round(target_calories, 0),
            "mode": str(user_data.get("mode", "hinglish")).lower()}


def extract_drink_info(msg: str) -> Optional[Dict[str, Any]]:
    msg_clean = msg.lower().strip()
    matched_label, mapped = None, None

    for brand in sorted(BRAND_MAPPINGS.keys(), key=len, reverse=True):
        if brand in msg_clean:
            matched_label, mapped = brand.title(), BRAND_MAPPINGS[brand]
            break

    if not mapped and not ALCOHOL_DF.empty:
        drinks = sorted(ALCOHOL_DF["Drink"].dropna().tolist(), key=len, reverse=True)
        for d in drinks:
            if str(d).lower() in msg_clean:
                matched_label, mapped = d, {"base": d, "std_ml": 30, "cal_per_30ml": 65}
                break

    if not mapped:
        for term in ["whiskey", "whisky", "beer", "vodka", "rum", "gin", "wine",
                     "cocktail", "brandy", "tequila", "cider", "champagne"]:
            if term in msg_clean:
                matched_label = term.capitalize()
                mapped = {"base": term.capitalize(),
                          "std_ml": 30 if term != "beer" else 330,
                          "cal_per_30ml": 65 if term != "beer" else 13}
                break

    if not mapped:
        return None

    vol = re.search(r'(\d+(?:\.\d+)?)\s*ml\b', msg_clean)
    qty = re.search(r'(\d+)\s*(peg|pegs|glass|glasses|pint|pints|shot|shots|drink|drinks|bottle|bottles|can|cans|cup|cups)', msg_clean)
    user_ml = float(vol.group(1)) if vol else None
    user_qty = float(qty.group(1)) if qty else None

    total_ml = user_ml if user_ml else (user_qty * mapped["std_ml"] if user_qty else mapped["std_ml"])
    total_cal = round((total_ml / 30.0) * mapped["cal_per_30ml"], 1)
    return {"drink": matched_label, "base_category": mapped["base"],
            "user_volume_ml": total_ml, "user_quantity": user_qty or 1, "calories": total_cal}


def recommend_meal_options(meal_slot: str, calorie_budget: float, diet_pref: str = "veg") -> List[Dict[str, Any]]:
    res = FOOD_DF.copy()
    res = res[res["food_type"] == "dish"]
    if diet_pref.lower().startswith("veg"):
        res = res[res["veg_flag"].str.lower() == "veg"]
    slot = res[res["meal_slots"].str.contains(meal_slot, case=False, na=False)]
    if not slot.empty:
        res = slot
    res = res[res["serv_energy"] <= (calorie_budget + 120)]
    if res.empty:
        res = FOOD_DF[FOOD_DF["food_type"] == "dish"].head(3)
    res = res.sample(min(3, len(res))) if len(res) > 3 else res
    return [{"food_name": r["food_name"], "calories": float(r["serv_energy"]),
             "protein_g": float(r["serv_protein"]), "carbs_g": float(r["serv_carb"]),
             "fat_g": float(r["serv_fat"])} for _, r in res.iterrows()]


def format_mapo_response(parsed: Dict[str, Any], profile: Dict[str, Any]) -> str:
    mode = profile.get("mode", "hinglish")
    t = parsed.get("type")

    if t == "alcohol":
        d = parsed["data"]
        if mode == "hinglish":
            return (f"Haanji, koi baat nahi! Outings aur fun moments toh life ka part hain — "
                    f"ek outing se aapki poori progress kharab nahi hoti.\n\n"
                    f"Aapne lagbhag **{d['user_volume_ml']:.0f}ml {d['drink']}** se "
                    f"**{d['calories']:.0f} kcal** consume kiye. Bas ab dinner thoda light rakhenge "
                    f"aur protein par focus karenge. Guilt bilkul mat feel kariye ji!")
        return (f"No worries at all! Enjoying a drink with friends is part of life, and one "
                f"social event won't undo your progress.\n\n"
                f"You consumed roughly **{d['calories']:.0f} kcal** from **{d['user_volume_ml']:.0f}ml "
                f"of {d['drink']}**. Let's keep the rest of your meals lighter and protein-forward. "
                f"Consistency over perfection!")

    if t == "meal_recommendation":
        opts = "\n".join([f"• **{o['food_name']}** — ~{o['calories']:.0f} kcal | {o['protein_g']:.0f}g protein"
                          for o in parsed["data"]])
        if mode == "hinglish":
            return (f"Bilkul ji! Aapke targets ke hisaab se yeh badiya balanced options hain:\n\n{opts}\n\n"
                    f"Inme se apni pasand ka choose kar lijiye — satiety bhi milegi aur protein goals bhi poore honge!")
        return (f"Here are a few tailored options that fit your remaining budget:\n\n{opts}\n\n"
                f"Pick whichever sounds best — they'll keep you full and hit your protein goals!")

    if t == "junk_food_preference":
        if mode == "hinglish":
            return ("Koi baat nahi ji! Aapko wahi khilana hai jo aapko pasand hai. Better portions aur "
                    "cleaner swaps ke saath hum aapke calorie aur protein targets ke andar reh kar consistency maintain karenge!")
        return ("Not a problem! No need to force foods you dislike. We'll fit your comfort foods in by "
                "managing portions and prioritising protein.")

    if mode == "hinglish":
        return (f"Haanji {profile['name']}! Main aapki nutrition journey me help ke liye taiyar hoon. "
                f"Bataiye aaj kya khaya ya kya khana plan kar rahe hain — hum milkar adjust kar lenge! "
                f"(Aapka daily target ~{profile['target_calories']:.0f} kcal hai.)")
    return (f"Hello {profile['name']}! I'm here to support your nutrition journey. Tell me what you ate "
            f"or plan to eat and we'll keep it balanced. (Your daily target is ~{profile['target_calories']:.0f} kcal.)")


def process_user_query(user_message: str, user_profile_input: Dict[str, Any]) -> str:
    profile = calculate_user_profile_targets(user_profile_input)
    msg = user_message.lower()

    drink = extract_drink_info(user_message)
    if drink:
        parsed = {"type": "alcohol", "data": drink}
    elif any(k in msg for k in ["junk", "pizza", "burger", "fries"]):
        parsed = {"type": "junk_food_preference"}
    elif any(k in msg for k in ["eat", "dinner", "lunch", "breakfast", "suggest", "recommend", "snack"]):
        slot = "dinner"
        if "lunch" in msg:
            slot = "lunch"
        elif "breakfast" in msg:
            slot = "breakfast"
        elif "snack" in msg or "high tea" in msg:
            slot = "high tea"
        meals = recommend_meal_options(slot, profile["target_calories"] * 0.35,
                                       user_profile_input.get("diet_preference", "veg"))
        parsed = {"type": "meal_recommendation", "data": meals}
    else:
        parsed = {"type": "general"}

    return format_mapo_response(parsed, profile)
