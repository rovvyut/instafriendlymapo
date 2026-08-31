"""MAPO backend API tests - covers root, diet, chat, feed, auth, logs."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://nutriflow-3d.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


# ---------------- fixtures ----------------
@pytest.fixture(scope="session")
def s():
    ses = requests.Session()
    ses.headers.update({"Content-Type": "application/json"})
    return ses


@pytest.fixture(scope="session")
def new_user(s):
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    r = s.post(f"{API}/auth/register", json={"name": "Test User", "email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    data = r.json()
    return {"email": email, "password": "secret123", "token": data["token"], "user": data["user"]}


@pytest.fixture(scope="session")
def auth_headers(new_user):
    return {"Authorization": f"Bearer {new_user['token']}"}


# ---------------- root ----------------
def test_root_ok(s):
    r = s.get(f"{API}/")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------- diet plan ----------------
def test_diet_plan(s):
    payload = {
        "name": "Rohan", "weight": 78, "height": 175, "age": 28, "gender": "Male",
        "activity_level": 3, "goal": 3, "target_weight": 70,
        "meal_preference": "vegetarian", "early_morning_choice": "Lemon Ginger Water",
        "cuisines": [], "dislikes": [],
    }
    r = s.post(f"{API}/diet/plan", json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ["bmi", "bmr", "tdee", "target_calories", "macros", "meals", "daily_totals"]:
        assert k in d
    assert set(["protein", "carbs", "fat"]).issubset(d["macros"].keys())
    slots = [m["slot"] for m in d["meals"]]
    assert slots == ["early morning", "breakfast", "lunch", "high tea", "dinner"]
    for m in d["meals"]:
        assert "foods" in m and "totals" in m
    # daily total energy close to target
    ratio = d["daily_totals"]["energy"] / d["target_calories"]
    assert 0.6 <= ratio <= 1.4, f"daily energy {d['daily_totals']['energy']} vs target {d['target_calories']}"


# ---------------- chat ----------------
def test_chat_alcohol_hinglish(s):
    r = s.post(f"{API}/chat", json={
        "message": "I had 2 pegs of old monk",
        "user_profile": {"name": "Rohan", "mode": "hinglish"},
    })
    assert r.status_code == 200
    reply = r.json()["response"].lower()
    assert "kcal" in reply
    assert any(w in reply for w in ["haanji", "guilt", "old monk", "dark rum"])


def test_chat_meal_english(s):
    r = s.post(f"{API}/chat", json={
        "message": "suggest dinner",
        "user_profile": {"name": "Rohan", "mode": "english"},
    })
    assert r.status_code == 200
    reply = r.json()["response"]
    assert "kcal" in reply.lower()


def test_chat_general(s):
    r = s.post(f"{API}/chat", json={
        "message": "hi",
        "user_profile": {"name": "Rohan", "mode": "hinglish"},
    })
    assert r.status_code == 200
    assert "rohan" in r.json()["response"].lower()


# ---------------- feed ----------------
def test_feed(s):
    r = s.get(f"{API}/feed?limit=12")
    assert r.status_code == 200
    d = r.json()
    assert "posts" in d and "stories" in d
    assert len(d["posts"]) == 12
    assert len(d["stories"]) == 6
    p = d["posts"][0]
    for k in ["dish_name", "calories", "protein", "carbs", "fat", "image", "tags", "author", "avatar"]:
        assert k in p, f"missing {k}"


# ---------------- auth ----------------
def test_register_duplicate(s, new_user):
    r = s.post(f"{API}/auth/register",
               json={"name": "x", "email": new_user["email"], "password": "secret123"})
    assert r.status_code == 400


def test_login_ok(s, new_user):
    r = s.post(f"{API}/auth/login",
               json={"email": new_user["email"], "password": new_user["password"]})
    assert r.status_code == 200
    assert "token" in r.json()


def test_login_wrong_password(s, new_user):
    r = s.post(f"{API}/auth/login",
               json={"email": new_user["email"], "password": "wrongpass"})
    assert r.status_code == 401


def test_me(s, auth_headers, new_user):
    r = s.get(f"{API}/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["email"] == new_user["email"]


def test_profile_update(s, auth_headers):
    r = s.put(f"{API}/auth/profile", headers=auth_headers,
              json={"profile": {"height": 175, "weight": 78}})
    assert r.status_code == 200
    assert r.json()["profile"]["height"] == 175


def test_admin_login(s):
    r = s.post(f"{API}/auth/login",
               json={"email": "coach@mapo.app", "password": "MAPO@2026"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "admin"


# ---------------- logs ----------------
def test_logs_unauth(s):
    r = s.get(f"{API}/logs")
    assert r.status_code == 401


def test_logs_crud(s, auth_headers):
    r = s.post(f"{API}/logs", headers=auth_headers,
               json={"dish_name": "TEST_Dal", "calories": 210, "protein": 12, "carbs": 30, "fat": 4})
    assert r.status_code == 200, r.text
    log_id = r.json()["id"]

    r2 = s.get(f"{API}/logs", headers=auth_headers)
    assert r2.status_code == 200
    d = r2.json()
    assert any(l["id"] == log_id for l in d["logs"])
    assert d["totals"]["calories"] >= 210

    r3 = s.delete(f"{API}/logs/{log_id}", headers=auth_headers)
    assert r3.status_code == 200

    r4 = s.get(f"{API}/logs", headers=auth_headers)
    assert not any(l["id"] == log_id for l in r4.json()["logs"])
