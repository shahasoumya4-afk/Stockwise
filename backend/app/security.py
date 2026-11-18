"""
Authentication helpers: password hashing (bcrypt), signed tokens (JWT), login throttling and the
dependencies that protect the API. Accounts live in the PostgreSQL `users` table.

Every /api route requires a valid token for an ACTIVE user, except the public paths below
(signup, login, signup options). The user is re-read from the database on every request, so
disabling an account or changing a role takes effect immediately.

Environment: JWT_SECRET (required in production), ACCESS_TOKEN_MINUTES (default 480).
"""
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer

from . import db

log = logging.getLogger("auth")
ALGORITHM = "HS256"
PUBLIC_PATHS = {"/", "/health", "/docs", "/redoc", "/openapi.json",
                "/api/auth/signup", "/api/auth/login", "/api/auth/token", "/api/auth/options"}
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)
_state = {"secret": None, "dummy": None}


def _secret() -> str:
    if _state["secret"] is None:
        _state["secret"] = os.getenv("JWT_SECRET") or ""
        if len(_state["secret"]) < 32:
            if _state["secret"]:
                log.warning("JWT_SECRET is shorter than 32 characters; using a random secret instead.")
            else:
                log.warning("JWT_SECRET is not set: using a random secret (all logins reset on restart). Set it in production.")
            _state["secret"] = secrets.token_urlsafe(48)
    return _state["secret"]


def access_token_seconds() -> int:
    return int(os.getenv("ACCESS_TOKEN_MINUTES", "480")) * 60


# ------------------------------------------------------------------ passwords
def validate_password(pw: str) -> None:
    """Raise ValueError with a user-readable message when the password is not acceptable."""
    if len(pw) < 10:
        raise ValueError("Password must be at least 10 characters.")
    if len(pw.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes (bcrypt limit).")
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        raise ValueError("Password must contain at least one letter and one digit.")


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(pw: str, hashed: Optional[str]) -> bool:
    """Constant-effort check: always runs bcrypt, even for unknown users or unusable hashes."""
    if _state["dummy"] is None:
        _state["dummy"] = hash_password("dummy-password-for-timing-1")
    try:
        target = hashed if hashed and hashed.startswith("$2") else _state["dummy"]
        ok = bcrypt.checkpw(pw.encode("utf-8")[:72], target.encode("ascii"))
        return ok and target is hashed
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------------ tokens
def create_token(user_id: int, role_code: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "role": role_code, "iat": now, "exp": now + timedelta(seconds=access_token_seconds())}
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired. Please log in again.", headers={"WWW-Authenticate": "Bearer"})
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid token.", headers={"WWW-Authenticate": "Bearer"})


# ------------------------------------------------------------------ login throttling (per process)
_failures: dict = {}
MAX_FAILURES, WINDOW_SECONDS = 5, 15 * 60


def throttle_check(key: str) -> None:
    now = time.time()
    recent = [t for t in _failures.get(key, []) if now - t < WINDOW_SECONDS]
    _failures[key] = recent
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")


def throttle_fail(key: str) -> None:
    _failures.setdefault(key, []).append(time.time())


def throttle_clear(key: str) -> None:
    _failures.pop(key, None)


# ------------------------------------------------------------------ request protection
USER_SQL = """SELECT u.user_id, u.full_name, u.email, u.employee_id, u.account_status, d.name AS department,
                     r.role_code, r.display_name AS role_name
              FROM users u
              LEFT JOIN roles r ON r.role_id = u.assigned_role_id
              LEFT JOIN departments d ON d.department_id = u.department_id"""


def authenticate(request: Request, token: Optional[str] = Depends(oauth2_scheme), cur=Depends(db.get_cursor)):
    """App-wide dependency: public paths pass; everything else needs a valid token for an Active user."""
    if request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
        return None
    if not token:
        raise HTTPException(401, "Not authenticated.", headers={"WWW-Authenticate": "Bearer"})
    payload = decode_token(token)
    try:
        uid = int(payload["sub"])
    except ValueError:
        raise HTTPException(401, "Invalid token.", headers={"WWW-Authenticate": "Bearer"})
    cur.execute(USER_SQL + " WHERE u.user_id = %s", (uid,))
    user = cur.fetchone()
    if not user or user["account_status"] != "Active" or not user["role_code"]:
        raise HTTPException(401, "Account is not active.", headers={"WWW-Authenticate": "Bearer"})
    request.state.user = user
    return user


def require_admin(request: Request):
    user = getattr(request.state, "user", None)
    if not user or user["role_code"] != "ADMIN":
        raise HTTPException(403, "Administrator access required.")
    return user


def permissions_for(role_code: str) -> list:
    """Role -> capabilities shown to the front end (v1: everyone reads; only ADMIN manages accounts)."""
    perms = ["view_dashboard", "view_risk", "view_inventory", "view_purchase_orders", "preview_estimates"]
    if role_code == "ADMIN":
        perms.append("manage_users")
    if role_code in {"ADMIN", "INVENTORY_MANAGER"}:
        perms.append("manage_inventory")
    return perms
