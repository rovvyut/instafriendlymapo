"""Loads the MAPO food + alcohol databases once and exposes helpers."""
import os
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

FOOD_PATH = os.path.join(DATA_DIR, "food_database.csv")
ALCOHOL_PATH = os.path.join(DATA_DIR, "alcoholic_drinks.csv")


def _load_food():
    df = pd.read_csv(FOOD_PATH)
    for col in ["energy_kcal", "protein_g", "carb_g", "fat_g", "fibre_g",
                "serving_grams", "unit_serving_energy_kcal"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["unit_serving_energy_kcal"])
    # per-serving macros (base columns are per 100g)
    factor = df["serving_grams"].fillna(100) / 100.0
    df["serv_protein"] = (df["protein_g"].fillna(0) * factor).round(1)
    df["serv_carb"] = (df["carb_g"].fillna(0) * factor).round(1)
    df["serv_fat"] = (df["fat_g"].fillna(0) * factor).round(1)
    df["serv_energy"] = df["unit_serving_energy_kcal"].round(1)
    df["meal_slots"] = df["meal_slots"].fillna("")
    df["veg_flag"] = df["veg_flag"].fillna("veg")
    df["cuisine_region"] = df["cuisine_region"].fillna("Pan-Indian")
    df["food_type"] = df["food_type"].fillna("dish")
    return df


def _load_alcohol():
    try:
        df = pd.read_csv(ALCOHOL_PATH)
        df = df[[c for c in df.columns if not str(c).startswith("Unnamed")]]
        df["Calories"] = pd.to_numeric(df["Calories"], errors="coerce")
        return df.dropna(subset=["Calories"])
    except Exception:
        return pd.DataFrame()


FOOD_DF = _load_food()
ALCOHOL_DF = _load_alcohol()


def veg_mask(df, meal_preference: str):
    """Return boolean mask for a dietary preference."""
    pref = (meal_preference or "vegetarian").lower()
    flag = df["veg_flag"].str.lower()
    if pref.startswith("veg"):
        return flag == "veg"
    if pref == "egg":
        return flag.isin(["veg", "egg"])
    return flag.notna()  # non-vegetarian => everything
