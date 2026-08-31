"""Builds the social feed + stories from the food database.

Dish photography was removed: those images lived on a third-party CDN we do not
control, and the UI never rendered them. `categorize()` is kept because the
keyword label is still useful, it just no longer maps to a picture.
"""
import random
from mapo_data import FOOD_DF


KEYWORD_RULES = [
    ("dessert", ["halwa", "halva", "jamun", "barfi", "burfi", "laddu", "ladoo", "kheer",
                 "jalebi", "rasgulla", "rasmalai", "gujiya", "peda", "sandesh",
                 "mithai", "phirni", "kulfi", "gajar ka", "sheera", "payasam", "mysore pak",
                 "khoya", "malpua", "modak", "shrikhand", "custard", "cake", "cookie",
                 "brownie", "ice cream", "pudding", "chikki", "sohan", "petha", "rabri", "basundi"]),
    ("lassi", ["lassi", "smoothie", "milkshake", "shake", "thandai", "buttermilk", "chaas", "chhaas"]),
    ("tea", ["chai", "tea", "coffee", "kadha", "kahwa"]),
    ("juice", ["juice", "panna", "sherbet", "sharbat", "shikanji", "nimbu", "lemonade",
               "jaljeera", "aam panna", "coconut water", "infused water", "lemon ginger",
               "cumin infused", "water"]),
    ("soup", ["soup", "shorba", "rasam", "canjee", "conjee", "congee"]),
    ("salad", ["salad", "raita", "kachumber", "sprout", "koshimbir"]),
    ("paneer", ["paneer", "cottage cheese", "tofu"]),
    ("egg", ["egg", "omelet", "omelette", "anda", "bhurji"]),
    ("nonveg", ["chicken", "mutton", "lamb", "fish", "prawn", "shrimp", "meat", "keema",
                "kheema", "tandoori", "seekh", "kebab", "kabab", "gosht", "murgh", "macher",
                "macchi", "machli", "crab", "pork", "beef"]),
    ("rice", ["biryani", "biriyani", "pulao", "pulav", "fried rice", "jeera rice",
              "curd rice", "lemon rice", "steamed rice", "rice"]),
    ("bread", ["roti", "chapati", "chapathi", "paratha", "parantha", "naan", "poori",
               "puri", "kulcha", "thepla", "bhakri", "dosa", "idli", "uttapam", "appam",
               "dhokla", "phulka", "bhatura"]),
    ("snack", ["samosa", "pakora", "pakoda", "tikki", "vada", "wada", "kachori", "chaat",
               "bhel", "sev", "namkeen", "cutlet", "frankie", "spring roll", "momo",
               "sandwich", "toast", "fries", "chips", "puff", "roll", "fritter"]),
    ("dal", ["dal", "daal", "dhal", "sambar", "sambhar", "rajma", "chole", "chana",
             "chhole", "kadhi", "korma", "makhani", "kofta", "curry", "gravy", "masala",
             "kadai", "kadhai", "butter"]),
    ("sabzi", ["sabzi", "subzi", "sabji", "bhindi", "aloo", "gobi", "baingan", "bharta",
               "matar", "methi", "palak", "saag", "mushroom", "capsicum", "karela", "lauki",
               "tinda", "torai", "cabbage", "carrot", "beans", "bhaji", "vegetable", "veg"]),
]


def categorize(name: str) -> str:
    n = (name or "").lower()
    for category, keywords in KEYWORD_RULES:
        for kw in keywords:
            if kw in n:
                return category
    return "thali"


COACH_AVATARS = [
    "https://images.unsplash.com/photo-1763701502912-f3db0ee451da?crop=entropy&cs=srgb&fm=jpg&q=85&w=400",
    "https://images.unsplash.com/photo-1764971590992-6cb000c079ac?crop=entropy&cs=srgb&fm=jpg&q=85&w=400",
    "https://images.unsplash.com/photo-1764698072833-dd137d82bbba?crop=entropy&cs=srgb&fm=jpg&q=85&w=400",
    "https://images.pexels.com/photos/17232317/pexels-photo-17232317.jpeg?auto=compress&cs=tinysrgb&dpr=2&w=400",
    "https://images.pexels.com/photos/17924324/pexels-photo-17924324.jpeg?auto=compress&cs=tinysrgb&dpr=2&w=400",
    "https://images.unsplash.com/photo-1750698545009-679820502908?crop=entropy&cs=srgb&fm=jpg&q=85&w=400",
]

AUTHORS = [
    ("Anaya Kapoor", "@anaya.eats"), ("Rohan Mehta", "@rohanfit"),
    ("Priya Sharma", "@priya.macros"), ("Vikram Singh", "@vik.gains"),
    ("Neha Reddy", "@neha.nourish"), ("Arjun Nair", "@arjun.lean"),
]

CAPTIONS = [
    "Meal-prep Sunday sorted. Clean macros, big flavour. 🔥",
    "Progress > perfection. Logged and loving it.",
    "This one hits the protein target without the guilt.",
    "Diet Coach approved. Balanced and delicious.",
    "Fuel that feels like a treat. Ghar ki quality, gym-ready macros.",
    "Small swaps, big results. Consistency is everything.",
]


def _tags(row):
    tags = [row["cuisine_region"]]
    if row["veg_flag"] == "veg":
        tags.append("Veg")
    elif row["veg_flag"] == "egg":
        tags.append("Eggetarian")
    else:
        tags.append("High Protein")
    if row["serv_protein"] >= 12:
        tags.append("Protein Rich")
    if row["serv_energy"] <= 200:
        tags.append("Low Cal")
    if row["serv_carb"] <= 20:
        tags.append("Low Carb")
    return tags[:4]


def build_feed(n=12, seed=None):
    rng = random.Random(seed)
    pool = FOOD_DF[(FOOD_DF["food_type"] == "dish") & (FOOD_DF["serv_energy"] >= 120)]
    rows = pool.sample(min(n, len(pool)), random_state=seed).to_dict("records")
    posts = []
    for i, r in enumerate(rows):
        author, handle = rng.choice(AUTHORS)
        posts.append({
            "id": str(r["food_code"]) if "food_code" in r else str(i),
            "author": author, "handle": handle,
            "avatar": COACH_AVATARS[i % len(COACH_AVATARS)],
            "dish_name": r["food_name"], "cuisine": r["cuisine_region"],
            "category": categorize(r["food_name"]),
            "calories": round(r["serv_energy"], 0),
            "protein": round(r["serv_protein"], 1),
            "carbs": round(r["serv_carb"], 1),
            "fat": round(r["serv_fat"], 1),
            "serving": r["servings_unit"],
            "tags": _tags(r),
            "caption": rng.choice(CAPTIONS),
            "likes": rng.randint(214, 9800),
        })
    return posts


def search_feed(q, limit=25):
    ql = (q or "").strip().lower()
    if not ql:
        return []
    pool = FOOD_DF[(FOOD_DF["food_type"] == "dish") &
                   (FOOD_DF["food_name"].str.lower().str.contains(ql, na=False))]
    rows = pool.head(limit).to_dict("records")
    posts = []
    for i, r in enumerate(rows):
        author, handle = AUTHORS[i % len(AUTHORS)]
        posts.append({
            "id": str(r["food_code"]) if "food_code" in r else str(i),
            "author": author, "handle": handle,
            "avatar": COACH_AVATARS[i % len(COACH_AVATARS)],
            "dish_name": r["food_name"], "cuisine": r["cuisine_region"],
            "category": categorize(r["food_name"]),
            "calories": round(r["serv_energy"], 0), "protein": round(r["serv_protein"], 1),
            "carbs": round(r["serv_carb"], 1), "fat": round(r["serv_fat"], 1),
            "serving": r["servings_unit"], "tags": _tags(r),
            "caption": CAPTIONS[i % len(CAPTIONS)], "likes": 0,
        })
    return posts


def build_stories():
    titles = [
        ("Daily Meal Logs", "log"), ("Macro Achievements", "trophy"),
        ("Diet Coach Tips", "sparkles"), ("Hydration", "droplet"),
        ("Protein Wins", "beef"), ("Cheat Day Balance", "cookie"),
    ]
    return [{"id": f"story-{i}", "title": t, "icon": ic, "avatar": COACH_AVATARS[i % len(COACH_AVATARS)]}
            for i, (t, ic) in enumerate(titles)]
