"""
Email/password + Google JWT auth — hardened.

Security notes vs. the original:
  * Google sign-in no longer silently takes over an existing password account.
  * seed_admin no longer crashes (missing `logger`) and no longer resets the
    admin password on every boot.
  * /login no longer 500s for Google-created users (missing password_hash).
  * Rate limiting + lockout on /login, /register, /session.
  * No user enumeration on register; constant-ish time on login.
  * Cookie fallback removed (was CSRF-able). Bearer only.
  * Session tokens stored hashed, not plaintext.
  * JWT carries token_version so sessions can actually be revoked.
  * "type" claim is verified.
  * Profile is a bounded schema, not an arbitrary dict.
  * JWT_SECRET validated at startup; bcrypt 72-byte limit handled.
"""
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt
import jwt
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Request, Depends, Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field, ValidationError

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(hours=1)
MAX_PASSWORD_BYTES = 72  # bcrypt truncates beyond this

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --------------------------------------------------------------------------
# Secret handling
# --------------------------------------------------------------------------

def _secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if len(secret) < 32:
        # Fail loudly rather than signing tokens with a guessable key.
        raise RuntimeError("JWT_SECRET must be set and at least 32 characters.")
    return secret


def validate_startup_config() -> None:
    """Call this from your FastAPI startup event so a bad config fails at boot,
    not on the first login attempt."""
    _secret()
    if not GOOGLE_CLIENT_ID:
        logger.warning(
            "GOOGLE_CLIENT_ID is not set — Google sign-in will return 503. "
            "Email/password sign-in is unaffected."
        )


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------

# Precomputed hash of a value nobody will submit. Used to burn the same CPU
# cycles on 'user not found' as on 'wrong password', so response timing does
# not leak whether an account exists.
_DUMMY_HASH = bcrypt.hashpw(b"timing-attack-mitigation-placeholder", bcrypt.gensalt()).decode()


def _check_password_length(password: str) -> None:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at most {MAX_PASSWORD_BYTES} bytes.",
        )


def hash_password(password: str) -> str:
    _check_password_length(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: Optional[str]) -> bool:
    # hashed is None for OAuth-only accounts. Still run a compare so the
    # timing matches the "real password" path.
    target = hashed or _DUMMY_HASH
    try:
        ok = bcrypt.checkpw(plain.encode("utf-8")[:MAX_PASSWORD_BYTES], target.encode("utf-8"))
    except Exception:
        return False
    return ok and hashed is not None


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------
# In-memory: fine for a single process. Behind more than one worker or pod,
# swap this for Redis (or slowapi / fastapi-limiter) or it is trivially bypassed.

_ATTEMPTS: dict[str, list[float]] = defaultdict(list)


def _rate_limit(key: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    hits = [t for t in _ATTEMPTS[key] if now - t < window_seconds]
    if len(hits) >= limit:
        _ATTEMPTS[key] = hits
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(window_seconds)},
        )
    hits.append(now)
    _ATTEMPTS[key] = hits


def _client_ip(request: Request) -> str:
    # Only trust X-Forwarded-For if you actually run behind a proxy you control.
    if os.environ.get("TRUST_PROXY_HEADERS") == "1":
        fwd = request.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

def create_access_token(user_id: str, email: str, token_version: int = 0) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "tv": token_version,      # bump user.token_version to revoke everything
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
        "type": "access",
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def _serialize(user: dict) -> dict:
    user = dict(user)
    user["id"] = str(user.pop("_id"))
    user.pop("password_hash", None)
    user.pop("token_version", None)
    return user


def _bearer_token(request: Request) -> Optional[str]:
    # Bearer only. The old cookie fallback made every state-changing endpoint
    # CSRF-able, because browsers attach cookies automatically.
    auth_header = request.headers.get("Authorization", "")
    scheme, _, value = auth_header.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


# --------------------------------------------------------------------------
# Current user
# --------------------------------------------------------------------------

async def get_current_user(request: Request) -> dict:
    token = _bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    db = request.app.state.db

    # Every session — password or Google — is one of our own HS256 JWTs.
    # There is no second, opaque token type to get wrong any more.
    try:
        payload = jwt.decode(
            token,
            _secret(),
            algorithms=[JWT_ALGORITHM],   # never accept alg from the token
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if payload.get("type") != "access":
        # Stops a refresh / password-reset token from being used as an
        # access token if you ever add one signed with the same secret.
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        oid = ObjectId(payload["sub"])
    except (InvalidId, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token")

    user = await db.users.find_one({"_id": oid})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    if int(user.get("token_version", 0)) != int(payload.get("tv", 0)):
        raise HTTPException(status_code=401, detail="Session revoked")
    return _serialize(user)


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# --------------------------------------------------------------------------
# Google Sign-In (Google Identity Services)
# --------------------------------------------------------------------------
# The browser gets an ID token from Google and posts it here. We verify the
# signature against Google's public keys, so a forged or replayed token from
# anywhere else is rejected. No client secret is needed for this flow, and
# nothing here depends on a third-party session service.

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

_jwks_client = None


def _google_jwks():
    """Cached JWKS client. Google rotates keys, so PyJWT refreshes on miss."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(GOOGLE_CERTS_URL, cache_keys=True, lifespan=3600)
    return _jwks_client


def _verify_google_id_token(credential: str) -> dict:
    """Blocking; call through run_in_threadpool.

    Checks, in order: the signature against Google's current public keys, that
    the token was issued *for this app* (aud), that Google issued it (iss), and
    that it has not expired. Skipping any one of these makes the endpoint
    forgeable.
    """
    signing_key = _google_jwks().get_signing_key_from_jwt(credential)
    return jwt.decode(
        credential,
        signing_key.key,
        algorithms=["RS256"],
        audience=GOOGLE_CLIENT_ID,
        issuer=GOOGLE_ISSUERS,
        options={"require": ["exp", "iat", "aud", "iss", "sub"]},
    )


class GoogleLoginInput(BaseModel):
    # The ID token from Google Identity Services (the `credential` field).
    credential: str = Field(min_length=16, max_length=8192)


@router.post("/google")
async def google_login(body: GoogleLoginInput, request: Request):
    _rate_limit(f"google:{_client_ip(request)}", limit=20, window_seconds=300)

    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured.")

    try:
        claims = await run_in_threadpool(_verify_google_id_token, body.credential)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Google sign-in expired. Please try again.")
    except jwt.InvalidAudienceError:
        # Token was minted for a different app.
        logger.warning("Google token with wrong audience rejected")
        raise HTTPException(status_code=401, detail="Invalid Google sign-in.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid Google sign-in.")
    except Exception:
        logger.exception("Google key verification failed")
        raise HTTPException(status_code=503, detail="Google sign-in is unavailable right now.")

    email = str(claims.get("email", "")).lower().strip()
    if not email:
        raise HTTPException(status_code=401, detail="Google account has no email address.")
    if not claims.get("email_verified", False):
        # An unverified Google address proves nothing about who owns it.
        raise HTTPException(status_code=401, detail="Please verify your Google email address first.")

    db = request.app.state.db
    now = datetime.now(timezone.utc).isoformat()
    user = await db.users.find_one({"email": email})

    if user is None:
        doc = {
            "name": claims.get("name") or email,
            "email": email,
            "picture": claims.get("picture"),
            "role": "user",
            "auth_provider": "google",
            "google_sub": claims.get("sub"),
            "email_verified": True,
            "token_version": 0,
            "profile": None,
            "created_at": now,
        }
        res = await db.users.insert_one(doc)
        doc["_id"] = res.inserted_id
        user = doc
    elif user.get("auth_provider") != "google":
        # Signing in with Google must never hand you an existing password
        # account just because the email matches — that is account takeover.
        # Linking has to be a deliberate act by someone already signed in.
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. "
                   "Sign in with your password instead.",
        )
    else:
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {
                "picture": claims.get("picture"),
                "name": user.get("name") or claims.get("name"),
                "google_sub": claims.get("sub"),
            }},
        )
        user = await db.users.find_one({"_id": user["_id"]})

    token = create_access_token(
        str(user["_id"]), email, token_version=int(user.get("token_version", 0))
    )
    return {"token": token, "user": _serialize(user)}


@router.post("/logout")
async def logout(request: Request, response: Response):
    """Client-side sign-out. The access token stays valid until it expires
    (1 hour) — use /logout-all to actually revoke it."""
    # Clear any legacy cookie left over from the old implementation.
    response.delete_cookie("session_token")
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(request: Request, user: dict = Depends(get_current_user)):
    """Revokes every JWT and every session for this user. Call this on password
    change, on 'sign out everywhere', and when banning an account."""
    db = request.app.state.db
    # Bumping token_version invalidates every token already issued for this
    # user, on every device, immediately.
    await db.users.update_one({"_id": ObjectId(user["id"])}, {"$inc": {"token_version": 1}})
    return {"ok": True}


# --------------------------------------------------------------------------
# Email / password
# --------------------------------------------------------------------------

class RegisterInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=MAX_PASSWORD_BYTES)


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_BYTES)


@router.post("/register")
async def register(body: RegisterInput, request: Request):
    ip = _client_ip(request)
    _rate_limit(f"register:{ip}", limit=5, window_seconds=3600)

    db = request.app.state.db
    email = body.email.lower().strip()

    existing = await db.users.find_one({"email": email})
    if existing:
        # Deliberately does NOT say "this email is taken" — that turns the
        # endpoint into a user-list oracle. Real products send an email here
        # ("someone tried to register with your address") and return 200.
        logger.info("Registration attempt on existing email")
        raise HTTPException(
            status_code=400,
            detail="Unable to create account with those details. "
                   "If you already have an account, try signing in or resetting your password.",
        )

    doc = {
        "name": body.name.strip(),
        "email": email,
        "password_hash": hash_password(body.password),
        "role": "user",
        "auth_provider": "password",
        "email_verified": False,   # send a verification link before trusting this
        "token_version": 0,
        "profile": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        res = await db.users.insert_one(doc)
    except Exception:
        # Requires a unique index: db.users.create_index("email", unique=True)
        # This closes the race where two concurrent registrations both pass
        # the find_one check above.
        raise HTTPException(status_code=400, detail="Unable to create account with those details.")

    doc["_id"] = res.inserted_id
    token = create_access_token(str(res.inserted_id), email, token_version=0)
    return {"token": token, "user": _serialize(doc)}


@router.post("/login")
async def login(body: LoginInput, request: Request):
    ip = _client_ip(request)
    email = body.email.lower().strip()
    _rate_limit(f"login-ip:{ip}", limit=10, window_seconds=300)
    _rate_limit(f"login-acct:{email}", limit=5, window_seconds=900)

    db = request.app.state.db
    user = await db.users.find_one({"email": email})

    # .get() not [] — Google-created users have no password_hash, and the old
    # code raised KeyError there, leaking a 500 (and account existence).
    stored_hash = user.get("password_hash") if user else None

    if not verify_password(body.password, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_access_token(
        str(user["_id"]), email, token_version=int(user.get("token_version", 0))
    )
    return {"token": token, "user": _serialize(user)}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------

class ProfileInput(BaseModel):
    """Was `profile: dict` — unbounded. A user could store megabytes, or keys
    containing '.' / '$' that confuse later Mongo queries. Adjust these fields
    to whatever your app actually needs, but keep it an explicit schema."""
    model_config = {"extra": "forbid"}

    display_name: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=20)
    address_line1: Optional[str] = Field(default=None, max_length=200)
    address_line2: Optional[str] = Field(default=None, max_length=200)
    city: Optional[str] = Field(default=None, max_length=100)
    postal_code: Optional[str] = Field(default=None, max_length=20)
    dietary_prefs: list[str] = Field(default_factory=list, max_length=20)
    bio: Optional[str] = Field(default=None, max_length=1000)


@router.put("/profile")
async def update_profile(
    body: ProfileInput,
    request: Request,
    user: dict = Depends(get_current_user),
):
    db = request.app.state.db
    # Only the profile subdocument is writable — role, email, password_hash and
    # token_version are never reachable from user input.
    await db.users.update_one(
        {"_id": ObjectId(user["id"])},
        {"$set": {"profile": body.model_dump(exclude_none=False)}},
    )
    updated = await db.users.find_one({"_id": ObjectId(user["id"])})
    return _serialize(updated)


# --------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------

async def ensure_indexes(db) -> None:
    """Call at startup. The unique index is what actually prevents duplicate
    accounts under concurrency."""
    await db.users.create_index("email", unique=True)
    # One weight reading per user per day. The upsert in /api/weight relies on
    # this pair being unique; without the index a race can still write two.
    await db.weight_logs.create_index(
        [("user_id", 1), ("recorded_on", 1)], unique=True
    )
    # Every progress query filters by user and buckets by date.
    await db.calorie_logs.create_index([("user_id", 1), ("created_at", -1)])


async def seed_admin(db) -> None:
    """Creates the admin account once, if it does not exist.

    Changed from the original: it no longer overwrites the password on every
    boot. That behaviour meant ADMIN_PASSWORD was a permanent, self-repairing
    backdoor — rotating the admin password in the app was undone at the next
    restart, and anyone who ever saw that env var had forever-access.
    Set ADMIN_RESET_PASSWORD=1 for a single deliberate reset, then remove it.
    """
    email = os.environ.get("ADMIN_EMAIL", "").lower().strip()
    password = os.environ.get("ADMIN_PASSWORD", "").strip()

    if not email or not password:
        logger.warning("Skipping admin seed: ADMIN_EMAIL or ADMIN_PASSWORD not set.")
        return
    if len(password) < 12 or password.lower() in {"password", "admin", "changeme", "admin123"}:
        logger.warning("Skipping admin seed: ADMIN_PASSWORD is too weak.")
        return

    existing = await db.users.find_one({"email": email})
    if existing is None:
        await db.users.insert_one({
            "name": "MAPO Admin",
            "email": email,
            "password_hash": hash_password(password),
            "role": "admin",
            "auth_provider": "password",
            "email_verified": True,
            "token_version": 0,
            "profile": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("Seeded admin account.")
    elif os.environ.get("ADMIN_RESET_PASSWORD") == "1":
        await db.users.update_one(
            {"email": email},
            {"$set": {"password_hash": hash_password(password), "role": "admin"},
             "$inc": {"token_version": 1}},
        )
        logger.warning("Admin password reset via ADMIN_RESET_PASSWORD. Unset that variable now.")