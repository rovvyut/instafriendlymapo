import os
import time
import logging
import uuid
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone, date, timedelta
from typing import Optional, List

from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, HTTPException, Request, Depends, Body, Query
# Aliased: bare `Path` would shadow pathlib.Path, which is used above.
from fastapi import Path as PathParam
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from pydantic import BaseModel, Field

from auth import (
    router as auth_router,
    seed_admin,
    ensure_indexes,
    validate_startup_config,
    get_current_user,
    require_admin,
)
from nutrition import (
    DietRequest,
    DietResponse,
    WeeklyDietRequest,
    WeeklyDietResponse,
    generate_diet_plan,
    generate_weekly_plan,
    swap_food,
)
from mapo_chatbot import process_user_query
from ai_coach import coach_reply
from feed import build_feed, build_stories, search_feed
from food_components import COMPONENTS, get_dish, list_dishes
import recipes

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("mapo")

IS_PRODUCTION = os.environ.get("ENVIRONMENT", "development").lower() == "production"

client = AsyncIOMotorClient(
    os.environ["MONGO_URL"],
    maxPoolSize=50,
    minPoolSize=5,
    serverSelectionTimeoutMS=5000,
)
db = client[os.environ["DB_NAME"]]

app = FastAPI(
    title="MAPO Personalised Nutrition API",
    # Do not expose interactive API docs in production.
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)
app.state.db = db

api = APIRouter(prefix="/api")


# --------------------------- Client IP helper ---------------------------
def client_ip(request: Request) -> str:
    """Only trust X-Forwarded-For when we know we are behind a proxy we control.
    Otherwise any client could spoof the header and bypass rate limits."""
    if os.environ.get("TRUST_PROXY_HEADERS") == "1":
        fwd = request.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --------------------------- Rate limiting ---------------------------
# In-memory, so it only holds within a single process. Behind multiple workers
# or pods, move this to Redis or it is trivially bypassed by hitting another
# instance.
_PUBLIC_HITS: dict = defaultdict(list)
PUBLIC_RATE_LIMIT = int(os.environ.get("PUBLIC_RATE_LIMIT", "120"))
PUBLIC_RATE_WINDOW = 300  # seconds


def rate_limit_public(request: Request, bucket: str) -> None:
    key = f"{bucket}:{client_ip(request)}"
    now = time.monotonic()
    hits = [t for t in _PUBLIC_HITS[key] if now - t < PUBLIC_RATE_WINDOW]
    if len(hits) >= PUBLIC_RATE_LIMIT:
        _PUBLIC_HITS[key] = hits
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please slow down and try again shortly.",
            headers={"Retry-After": str(PUBLIC_RATE_WINDOW)},
        )
    hits.append(now)
    _PUBLIC_HITS[key] = hits


# --------------------------- Middleware ---------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline browser hardening: stops clickjacking, MIME sniffing and
    referrer leakage, and pins what the page is allowed to load."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=(), payment=()"
        )
        # This API returns JSON only; nothing should ever frame or script it.
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        if IS_PRODUCTION:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        rid = getattr(request.state, "request_id", None)
        if rid:
            response.headers.setdefault("X-Request-ID", rid)
        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Tag every request so a log line can be tied to a user report."""

    async def dispatch(self, request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        return await call_next(request)


@api.get("/")
async def root():
    return {"status": "ok", "app": "MAPO Personalised Nutrition Engine"}


# --------------------------- Diet plan (Protected) ---------------------------
@api.post("/diet/plan", response_model=DietResponse)
async def diet_plan(req: DietRequest, user: dict = Depends(get_current_user)):
    try:
        return generate_diet_plan(req)
    except Exception:
        # Do not echo the exception back to the client; it can leak file paths,
        # library versions and query fragments. Log it, return something generic.
        logger.exception("diet plan failed")
        raise HTTPException(status_code=500, detail="Could not generate plan")


# ----------------------- Weekly diet plan (Protected) -----------------------
@api.post("/diet/plan/week", response_model=WeeklyDietResponse)
async def diet_plan_week(req: WeeklyDietRequest, user: dict = Depends(get_current_user)):
    """Seven days off one set of body numbers.

    Same BMI/BMR/TDEE/goal arithmetic as ``/diet/plan``; the days differ only in
    how the week's calories are distributed (training days up, rest days down by
    exactly as much) and in which dishes are drawn, so a week does not repeat
    itself. Generation is CPU-bound pandas work, so it runs off the event loop.
    """
    try:
        return await run_in_threadpool(generate_weekly_plan, req)
    except Exception:
        logger.exception("weekly diet plan failed")
        raise HTTPException(status_code=500, detail="Could not generate weekly plan")


# --------------------------- Coach chat (Protected) ---------------------------
class UserProfileSchema(BaseModel):
    name: Optional[str] = Field(default="Friend", max_length=100)
    age: Optional[int] = Field(default=25, ge=13, le=120)
    gender: Optional[str] = Field(default="male", max_length=20)
    height: Optional[float] = Field(default=170.0, gt=50, le=280)
    weight: Optional[float] = Field(default=70.0, gt=20, le=500)
    target_weight: Optional[float] = Field(default=65.0, gt=20, le=500)
    activity_level: Optional[int] = Field(default=2, ge=1, le=5)
    goal: Optional[int] = Field(default=3, ge=1, le=4)
    diet_preference: Optional[str] = Field(default="veg", max_length=40)
    mode: Optional[str] = Field(default="hinglish", max_length=20)


class ChatRequestSchema(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    user_profile: UserProfileSchema


@api.post("/chat")
async def chat_endpoint(payload: ChatRequestSchema, user: dict = Depends(get_current_user)):
    try:
        reply = process_user_query(payload.message, payload.user_profile.dict())
        return {"response": reply}
    except Exception:
        logger.exception("chat failed")
        raise HTTPException(status_code=500, detail="Chat is unavailable right now.")


# --------------------------- Feed & stories (public, rate limited) ---------------------------
@api.get("/feed")
async def get_feed(
    request: Request,
    limit: int = Query(default=12, ge=1, le=50),
    seed: int = Query(default=7, ge=0, le=10_000_000),
):
    rate_limit_public(request, "feed")
    return {"posts": build_feed(limit, seed=seed), "stories": build_stories()}


@api.get("/foods/search")
async def foods_search(
    request: Request,
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=25, ge=1, le=50),
):
    rate_limit_public(request, "search")
    return {"posts": search_feed(q, limit)}


# ------------------- Ingredient-level nutrition (public) -------------------
# The feed prices whole dishes. These two routes price a dish one layer at a
# time, which is what the burger anatomy and the pizza builder run on. Values
# come from the food database wherever it carries the row and from IFCT/USDA
# reference tables where it does not — see food_components.py.
@api.get("/foods/components")
async def food_components(request: Request):
    rate_limit_public(request, "components")
    return COMPONENTS


@api.get("/foods/components/{dish}")
async def food_component_dish(dish: str, request: Request):
    rate_limit_public(request, "components")
    found = get_dish(dish)
    if found is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown dish. Available: {', '.join(list_dishes())}",
        )
    return found


# --------------------------- Calorie logging (auth) ---------------------------
class LogInput(BaseModel):
    dish_name: str = Field(min_length=1, max_length=200)
    calories: float = Field(ge=0, le=10000)
    protein: float = Field(default=0, ge=0, le=2000)
    carbs: float = Field(default=0, ge=0, le=2000)
    fat: float = Field(default=0, ge=0, le=2000)
    source: Optional[str] = Field(default="feed", max_length=40)


@api.post("/logs")
async def add_log(body: LogInput, user: dict = Depends(get_current_user)):
    doc = body.dict()
    doc["user_id"] = user["id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.calorie_logs.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc


class BulkLogInput(BaseModel):
    """Log a whole meal or a whole day of a plan in one request."""
    items: List[LogInput] = Field(min_length=1, max_length=40)


@api.post("/logs/bulk")
async def add_logs_bulk(body: BulkLogInput, user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    docs = []
    for item in body.items:
        doc = item.dict()
        doc["user_id"] = user["id"]
        doc["created_at"] = now
        docs.append(doc)
    res = await db.calorie_logs.insert_many(docs)
    out = []
    for oid, doc in zip(res.inserted_ids, docs):
        doc["id"] = str(oid)
        doc.pop("_id", None)
        out.append(doc)
    return {"inserted": len(out), "logs": out,
            "calories": round(sum(d["calories"] for d in docs), 1)}


@api.get("/logs")
async def get_logs(
    limit: int = Query(default=200, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
):
    logs = (
        await db.calorie_logs.find({"user_id": user["id"]})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )
    total = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    out = []
    for l in logs:
        l["id"] = str(l.pop("_id"))
        out.append(l)
        for k in total:
            total[k] += float(l.get(k, 0) or 0)
    return {"logs": out, "totals": {k: round(v, 1) for k, v in total.items()}}


@api.delete("/logs/{log_id}")
async def delete_log(log_id: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(log_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Log not found")
    # The user_id filter is what stops one user deleting another user's log.
    res = await db.calorie_logs.delete_one({"_id": oid, "user_id": user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Log not found")
    return {"ok": True}


# ------------------- Body weight + progress aggregates -------------------
# The goal journey, the weekly rewind and the daily progress readout each need
# history the logs table alone does not carry. These three routes supply it
# from real records only: if nothing has been logged, they return empty series
# rather than a plausible-looking curve.
class WeightInput(BaseModel):
    weight_kg: float = Field(gt=20, le=400)
    recorded_on: Optional[str] = Field(default=None, max_length=10)
    note: Optional[str] = Field(default=None, max_length=200)


@api.post("/weight")
async def add_weight(body: WeightInput, user: dict = Depends(get_current_user)):
    day = body.recorded_on or datetime.now(timezone.utc).date().isoformat()
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="recorded_on must be YYYY-MM-DD.")

    doc = {
        "user_id": user["id"],
        "weight_kg": round(float(body.weight_kg), 2),
        "recorded_on": day,
        "note": body.note,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # One reading per day: a second entry corrects the first rather than
    # stacking two points on the same date and bending the trend line.
    await db.weight_logs.update_one(
        {"user_id": user["id"], "recorded_on": day},
        {"$set": doc},
        upsert=True,
    )
    return doc


@api.get("/weight")
async def get_weight(
    days: int = Query(default=180, ge=1, le=1000),
    user: dict = Depends(get_current_user),
):
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    rows = (
        await db.weight_logs.find({"user_id": user["id"], "recorded_on": {"$gte": cutoff}})
        .sort("recorded_on", 1)
        .to_list(1000)
    )
    series = [{"date": r["recorded_on"], "weight_kg": r["weight_kg"]} for r in rows]
    first = series[0]["weight_kg"] if series else None
    latest = series[-1]["weight_kg"] if series else None
    return {
        "series": series,
        "first": first,
        "latest": latest,
        "change_kg": round(latest - first, 2) if series else None,
    }


def _targets_from_plan(plan_doc: Optional[dict]) -> dict:
    """Pull the calorie and macro targets out of the most recent saved plan."""
    if not plan_doc:
        return {}
    plan = plan_doc.get("plan") or {}
    macros = plan.get("macros") or {}
    out = {}
    if plan.get("target_calories") is not None:
        out["calories"] = round(float(plan["target_calories"]))
    for key in ("protein", "carbs", "fat"):
        value = macros.get(key) or macros.get(f"{key}_g")
        if value is not None:
            try:
                out[key] = round(float(value))
            except (TypeError, ValueError):
                pass
    for key in ("bmr", "tdee"):
        if plan.get(key) is not None:
            out[key] = round(float(plan[key]))
    return out


@api.get("/progress/today")
async def progress_today(user: dict = Depends(get_current_user)):
    today = datetime.now(timezone.utc).date().isoformat()
    logs = await db.calorie_logs.find({"user_id": user["id"]}).to_list(2000)
    eaten = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    meals = []
    for entry in logs:
        if str(entry.get("created_at", ""))[:10] != today:
            continue
        for key in eaten:
            eaten[key] += float(entry.get(key, 0) or 0)
        meals.append({
            "dish_name": entry.get("dish_name"),
            "calories": round(float(entry.get("calories", 0) or 0)),
            "logged_at": entry.get("created_at"),
        })

    plan_doc = await db.diet_plans.find_one(
        {"user_id": user["id"]}, sort=[("created_at", -1)]
    )
    targets = _targets_from_plan(plan_doc)
    remaining = (
        round(targets["calories"] - eaten["calories"])
        if targets.get("calories") is not None
        else None
    )
    return {
        "date": today,
        "eaten": {k: round(v) for k, v in eaten.items()},
        "targets": targets,
        "remaining_calories": remaining,
        "meals": meals,
    }


@api.get("/progress/week")
async def progress_week(
    days: int = Query(default=7, ge=2, le=31),
    user: dict = Depends(get_current_user),
):
    logs = await db.calorie_logs.find({"user_id": user["id"]}).to_list(5000)
    today = datetime.now(timezone.utc).date()
    order = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    buckets = {
        day: {"date": day, "calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "entries": 0}
        for day in order
    }
    for entry in logs:
        day = str(entry.get("created_at", ""))[:10]
        bucket = buckets.get(day)
        if bucket is None:
            continue
        bucket["entries"] += 1
        for key in ("calories", "protein", "carbs", "fat"):
            bucket[key] += float(entry.get(key, 0) or 0)

    series = [
        {**b, **{k: round(b[k]) for k in ("calories", "protein", "carbs", "fat")}}
        for b in (buckets[day] for day in order)
    ]
    logged_days = sum(1 for b in series if b["entries"] > 0)
    totals = {
        key: round(sum(b[key] for b in series))
        for key in ("calories", "protein", "carbs", "fat")
    }
    averages = {
        key: round(totals[key] / logged_days) if logged_days else 0
        for key in totals
    }

    plan_doc = await db.diet_plans.find_one(
        {"user_id": user["id"]}, sort=[("created_at", -1)]
    )

    return {
        "series": series,
        "totals": totals,
        "averages": averages,
        "logged_days": logged_days,
        "days": days,
        # Consistency is days with anything logged, not days on target. Hitting
        # a number is not the habit being measured here; showing up is.
        "consistency_pct": round(logged_days / days * 100) if days else 0,
        "targets": _targets_from_plan(plan_doc),
    }


@api.get("/logs/trend")
async def logs_trend(
    days: int = Query(default=7, ge=1, le=90),
    user: dict = Depends(get_current_user),
):
    logs = await db.calorie_logs.find({"user_id": user["id"]}).to_list(2000)
    today = datetime.now(timezone.utc).date()
    buckets = {(today - timedelta(days=i)).isoformat(): 0.0 for i in range(days - 1, -1, -1)}
    for l in logs:
        d = str(l.get("created_at", ""))[:10]
        if d in buckets:
            buckets[d] += float(l.get("calories", 0) or 0)
    return {"trend": [{"date": k, "calories": round(v, 0)} for k, v in buckets.items()]}


# --------------------------- AI Coach ---------------------------
class CoachChatIn(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=120)
    message: str = Field(min_length=1, max_length=2000)
    mode: str = Field(default="hinglish", max_length=20)
    user_profile: UserProfileSchema


_coach_rate = {}
COACH_DAILY_LIMIT = 15          # messages per daily session
COACH_MIN_INTERVAL = 2.0        # seconds between messages (rate limit)


@api.post("/coach")
async def coach(payload: CoachChatIn, user: dict = Depends(get_current_user)):
    uid = user["id"]
    now = time.time()
    if now - _coach_rate.get(uid, 0) < COACH_MIN_INTERVAL:
        raise HTTPException(status_code=429, detail="You're messaging too fast — give the coach a second. 🙂")
    day = datetime.now(timezone.utc).date().isoformat()
    usage = await db.coach_usage.find_one({"user_id": uid, "date": day})
    count = usage["count"] if usage else 0
    if count >= COACH_DAILY_LIMIT:
        raise HTTPException(status_code=429, detail="Your AI coaching session for today has been used. Come back tomorrow! 🌙")
    _coach_rate[uid] = now
    sid = payload.session_id or f"{uid}-{day}"
    try:
        reply = await coach_reply(db, sid, payload.message, payload.user_profile.dict(), payload.mode)
    except Exception:
        logger.exception("coach failed")
        raise HTTPException(status_code=500, detail="Coach is unavailable right now.")
    await db.coach_usage.update_one(
        {"user_id": uid, "date": day},
        {"$inc": {"count": 1}, "$setOnInsert": {"user_id": uid, "date": day}},
        upsert=True,
    )
    return {"response": reply, "session_id": sid, "remaining": COACH_DAILY_LIMIT - (count + 1), "limit": COACH_DAILY_LIMIT}


@api.get("/coach/quota")
async def coach_quota(user: dict = Depends(get_current_user)):
    day = datetime.now(timezone.utc).date().isoformat()
    usage = await db.coach_usage.find_one({"user_id": user["id"], "date": day})
    used = usage["count"] if usage else 0
    return {"used": used, "limit": COACH_DAILY_LIMIT, "remaining": max(0, COACH_DAILY_LIMIT - used)}


# --------------------------- Recipes (Protected, cached) ---------------------------
# Generating a recipe costs an LLM call, so this is behind auth, rate limited,
# and capped per user per day. Once a dish has been generated it is served from
# MongoDB for everyone, forever, at no cost.
RECIPE_DAILY_LIMIT = int(os.environ.get("RECIPE_DAILY_LIMIT", "30"))


@api.get("/foods/{food_code}/recipe")
async def food_recipe(
    request: Request,
    food_code: str = PathParam(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$"),
    user: dict = Depends(get_current_user),
):
    """India-specific ingredients and method for one dish."""
    if not recipes.food_exists(food_code):
        raise HTTPException(status_code=404, detail="Dish not found")

    cached = await recipes.get_cached_recipe(db, food_code)
    if cached:
        return {"recipe": cached, "cached": True}

    # Only an actual generation counts against the user's daily budget.
    uid = user["id"]
    day = datetime.now(timezone.utc).date().isoformat()
    usage = await db.recipe_usage.find_one({"user_id": uid, "date": day})
    used = usage["count"] if usage else 0
    if used >= RECIPE_DAILY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="You've reached today's limit for new recipes. Try again tomorrow.",
        )

    try:
        recipe = await run_in_threadpool(recipes.build_recipe, food_code)
    except LookupError:
        raise HTTPException(status_code=404, detail="Dish not found")
    except Exception:
        logger.exception("recipe generation failed for %s", food_code)
        raise HTTPException(status_code=503, detail="Could not write that recipe right now.")

    await recipes.store_recipe(db, recipe)
    await db.recipe_usage.update_one(
        {"user_id": uid, "date": day},
        {"$inc": {"count": 1}, "$setOnInsert": {"user_id": uid, "date": day}},
        upsert=True,
    )

    payload = recipe.model_dump()
    return {"recipe": payload, "cached": False}


# --------------------------- Meal swap (Protected) ---------------------------
class SwapIn(BaseModel):
    slot: str = Field(min_length=1, max_length=40)
    target_energy: float = Field(gt=0, le=10000)
    meal_preference: str = Field(default="vegetarian", max_length=40)
    exclude: List[str] = Field(default_factory=list, max_length=50)
    cuisines: List[str] = Field(default_factory=list, max_length=50)


@api.post("/diet/swap")
async def diet_swap(body: SwapIn, user: dict = Depends(get_current_user)):
    item = swap_food(body.slot, body.target_energy, body.meal_preference, body.exclude, body.cuisines)
    if not item:
        raise HTTPException(status_code=404, detail="No alternative dish found")
    return item


# --------------------------- Diet plan history ---------------------------
MAX_PLAN_BYTES = 256 * 1024


@api.post("/plans")
async def save_plan(plan: dict = Body(...), user: dict = Depends(get_current_user)):
    # Without a cap, any logged-in user can fill the database one request at a
    # time. 256 KB is far more than a real plan needs.
    try:
        import json as _json
        if len(_json.dumps(plan)) > MAX_PLAN_BYTES:
            raise HTTPException(status_code=413, detail="Plan is too large.")
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Plan must be a JSON object.")
    doc = {"user_id": user["id"], "plan": plan, "created_at": datetime.now(timezone.utc).isoformat()}
    res = await db.diet_plans.insert_one(doc)
    return {"id": str(res.inserted_id), "created_at": doc["created_at"]}


@api.get("/plans")
async def list_plans(
    limit: int = Query(default=50, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    docs = await db.diet_plans.find({"user_id": user["id"]}).sort("created_at", -1).to_list(limit)
    return [{"id": str(d["_id"]), "created_at": d["created_at"], "plan": d["plan"]} for d in docs]


@api.delete("/plans/{plan_id}")
async def delete_plan(plan_id: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(plan_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Plan not found")
    res = await db.diet_plans.delete_one({"_id": oid, "user_id": user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"ok": True}


# --------------------------- Social signals (likes / bookmarks) ---------------------------
class ReactIn(BaseModel):
    post_id: str = Field(min_length=1, max_length=120)
    type: str = Field(pattern="^(like|bookmark)$")


@api.post("/reactions/toggle")
async def toggle_reaction(body: ReactIn, user: dict = Depends(get_current_user)):
    q = {"user_id": user["id"], "post_id": body.post_id, "type": body.type}
    existing = await db.reactions.find_one(q)
    if existing:
        await db.reactions.delete_one(q)
        return {"active": False}
    await db.reactions.insert_one({**q, "created_at": datetime.now(timezone.utc).isoformat()})
    return {"active": True}


@api.get("/reactions")
async def my_reactions(user: dict = Depends(get_current_user)):
    docs = await db.reactions.find({"user_id": user["id"]}).to_list(3000)
    return {
        "liked": [d["post_id"] for d in docs if d["type"] == "like"],
        "bookmarked": [d["post_id"] for d in docs if d["type"] == "bookmark"],
    }


# --------------------------- Admin: users ---------------------------
@api.get("/admin/users")
async def admin_users(admin: dict = Depends(require_admin)):
    docs = await db.users.find().sort("created_at", -1).to_list(1000)
    return [{"id": str(d["_id"]), "name": d.get("name"), "email": d.get("email"),
             "role": d.get("role", "user"), "created_at": d.get("created_at")} for d in docs]


app.include_router(auth_router)
app.include_router(api)

# Middleware runs outermost-last-added, so add these after the routers.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)

# CORS: an allowlist, not "*". A wildcard here lets any site on the internet
# call this API from a victim's browser.
_cors_raw = os.environ.get("CORS_ORIGINS", "").strip()
if _cors_raw:
    CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]
else:
    CORS_ORIGINS = ["http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Session-ID"],
    expose_headers=["X-Request-ID"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Anything not already an HTTPException becomes a generic 500 — no
    tracebacks, paths or driver messages returned to the caller."""
    rid = getattr(request.state, "request_id", None)
    logger.exception("unhandled error (request_id=%s)", rid)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error.", "request_id": rid},
    )


@app.on_event("startup")
async def startup():
    validate_startup_config()
    await ensure_indexes(db)
    await db.calorie_logs.create_index("user_id")
    await db.diet_plans.create_index("user_id")
    await db.reactions.create_index("user_id")
    await recipes.ensure_indexes(db)
    await seed_admin(db)
    if "*" in CORS_ORIGINS:
        logger.warning("CORS_ORIGINS contains '*' — every website can call this API.")
    if IS_PRODUCTION and any(o.startswith("http://") for o in CORS_ORIGINS):
        logger.warning("CORS_ORIGINS has a plain-http origin in production.")
    logger.info("MAPO API ready — indexes created, admin seeded, CORS=%s", CORS_ORIGINS)


@app.on_event("shutdown")
async def shutdown():
    client.close()
