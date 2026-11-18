"""
Account endpoints: signup (pending approval), login, current user, and administrator user management.

Flow: signup creates a Pending account (no token). An administrator approves it and assigns a role
(Active) or rejects it. Only Active accounts can log in. Passwords are stored as bcrypt hashes in
the PostgreSQL `users` table; tokens are stateless, so "logout" means the client discards its token.
The first administrator is created with `python create_admin.py` (never through signup).
"""
import re
from typing import Optional

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from . import db
from .common import SYNTHETIC_NOTICE, paged
from .security import (USER_SQL, access_token_seconds, create_token, hash_password, permissions_for, require_admin,
                       throttle_check, throttle_clear, throttle_fail, validate_password, verify_password)

router = APIRouter(prefix="/api/auth", tags=["accounts"])
admin = APIRouter(prefix="/api/admin", tags=["administration"], dependencies=[Depends(require_admin)])
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SIGNUP_ROLE_EXCLUDED = {"ADMIN"}  # administrators are created by an existing administrator, never by signup
Read, Write = Depends(db.get_cursor), Depends(db.get_write_cursor)


class SignupIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    employee_id: str = Field(min_length=2, max_length=30)
    email: str = Field(max_length=255)
    department_id: int
    requested_role_code: str = Field(max_length=40)
    password: str = Field(max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)


class ApproveIn(BaseModel):
    role_code: Optional[str] = Field(default=None, max_length=40, description="defaults to the requested role")


class RoleIn(BaseModel):
    role_code: str = Field(max_length=40)


def _user_payload(u: dict) -> dict:
    return {"user_id": u["user_id"], "full_name": u["full_name"], "email": u["email"], "employee_id": u["employee_id"],
            "department": u["department"], "role_code": u["role_code"], "role_name": u["role_name"],
            "status": u["account_status"], "permissions": permissions_for(u["role_code"])}


# ------------------------------------------------------------------ public
@router.get("/options")
def signup_options(cur=Read):
    """Departments and roles offered on the signup form, plus the password rules."""
    cur.execute("SELECT department_id, department_code, name FROM departments WHERE is_active ORDER BY department_id")
    deps = cur.fetchall()
    cur.execute("SELECT role_code, display_name, description FROM roles WHERE role_code <> ALL(%s) ORDER BY role_id",
                (list(SIGNUP_ROLE_EXCLUDED),))
    return {"departments": deps, "roles": cur.fetchall(),
            "password_rules": "At least 10 characters, at most 72 bytes, with at least one letter and one digit.",
            "notice": SYNTHETIC_NOTICE}


@router.post("/signup", status_code=201)
def signup(body: SignupIn, cur=Write):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    try:
        validate_password(body.password)
    except ValueError as e:
        raise HTTPException(422, str(e))
    cur.execute("SELECT role_id FROM roles WHERE role_code = %s AND role_code <> ALL(%s)",
                (body.requested_role_code, list(SIGNUP_ROLE_EXCLUDED)))
    role = cur.fetchone()
    if not role:
        raise HTTPException(422, "Choose one of the roles offered on the signup form.")
    cur.execute("SELECT 1 FROM departments WHERE department_id = %s AND is_active", (body.department_id,))
    if not cur.fetchone():
        raise HTTPException(422, "Unknown department.")
    employee_id = body.employee_id.strip()
    cur.execute("SELECT 1 FROM users WHERE lower(email) = %s OR employee_id = %s", (email, employee_id))
    if cur.fetchone():
        raise HTTPException(409, "An account with this email or employee ID already exists.")
    try:
        cur.execute("""INSERT INTO users (employee_id, full_name, email, password_hash, department_id, requested_role_id,
                                          assigned_role_id, account_status, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, NULL, 'Pending', now(), now()) RETURNING user_id""",
                    (employee_id, body.full_name.strip(), email, hash_password(body.password), body.department_id, role["role_id"]))
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(409, "An account with this email or employee ID already exists.")
    return {"user_id": cur.fetchone()["user_id"], "status": "Pending",
            "message": "Account created. An administrator must approve it before you can log in."}


def _login(email: str, password: str, request: Request, cur) -> dict:
    email = email.strip().lower()
    key = f"{request.client.host if request.client else '?'}|{email}"
    throttle_check(key)
    cur.execute("SELECT user_id, password_hash, account_status FROM users WHERE lower(email) = %s", (email,))
    row = cur.fetchone()
    if not verify_password(password, row["password_hash"] if row else None) or not row:
        throttle_fail(key)
        raise HTTPException(401, "Incorrect email or password.")
    status_messages = {"Pending": "Your account is awaiting administrator approval.",
                       "Rejected": "Your registration was not approved.", "Disabled": "Your account is disabled."}
    if row["account_status"] != "Active":
        raise HTTPException(403, status_messages.get(row["account_status"], "Your account is not active."))
    cur.execute(USER_SQL + " WHERE u.user_id = %s", (row["user_id"],))
    user = cur.fetchone()
    if not user["role_code"]:
        raise HTTPException(403, "Your account has no role assigned yet.")
    throttle_clear(key)
    return {"access_token": create_token(user["user_id"], user["role_code"]), "token_type": "bearer",
            "expires_in": access_token_seconds(), "user": _user_payload(user)}


@router.post("/login")
def login(body: LoginIn, request: Request, cur=Read):
    """JSON login for the dashboard."""
    return _login(body.email, body.password, request, cur)


@router.post("/token", include_in_schema=True)
def token_form(request: Request, form: OAuth2PasswordRequestForm = Depends(), cur=Read):
    """Form login used by the 'Authorize' button in /docs (username = email)."""
    return _login(form.username, form.password, request, cur)


# ------------------------------------------------------------------ signed-in users
@router.get("/me")
def me(request: Request):
    return _user_payload(request.state.user)


# ------------------------------------------------------------------ administrators
def _role_id(cur, role_code: str) -> int:
    cur.execute("SELECT role_id FROM roles WHERE role_code = %s", (role_code,))
    r = cur.fetchone()
    if not r:
        raise HTTPException(422, f"Unknown role '{role_code}'.")
    return r["role_id"]


def _target(cur, user_id: int) -> dict:
    cur.execute("""SELECT u.user_id, u.account_status, u.assigned_role_id, u.requested_role_id, u.password_hash, r.role_code
                   FROM users u LEFT JOIN roles r ON r.role_id = u.assigned_role_id WHERE u.user_id = %s FOR UPDATE OF u""", (user_id,))
    t = cur.fetchone()
    if not t:
        raise HTTPException(404, "User not found.")
    return t


def _other_active_admins(cur, exclude_user_id: int) -> int:
    cur.execute("""SELECT COUNT(*) AS n FROM users u JOIN roles r ON r.role_id = u.assigned_role_id
                   WHERE r.role_code = 'ADMIN' AND u.account_status = 'Active' AND u.user_id <> %s""", (exclude_user_id,))
    return cur.fetchone()["n"]


@admin.get("/users")
def list_users(status: Optional[str] = Query("Pending", pattern="^(Pending|Active|Rejected|Disabled)$"),
               limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), cur=Read):
    """Accounts by status (default: pending approvals). Seeded demo accounts are Disabled."""
    cur.execute("""SELECT u.user_id, u.full_name, u.email, u.employee_id, d.name AS department,
                          rq.role_code AS requested_role, ra.role_code AS assigned_role, u.account_status,
                          u.created_at, u.approved_at, COUNT(*) OVER() AS _total
                   FROM users u
                   LEFT JOIN departments d ON d.department_id = u.department_id
                   LEFT JOIN roles rq ON rq.role_id = u.requested_role_id
                   LEFT JOIN roles ra ON ra.role_id = u.assigned_role_id
                   WHERE (%(s)s IS NULL OR u.account_status = %(s)s)
                   ORDER BY u.created_at DESC, u.user_id DESC LIMIT %(l)s OFFSET %(o)s""", dict(s=status, l=limit, o=offset))
    return paged(cur.fetchall(), limit, offset)


@admin.post("/users/{user_id}/approve")
def approve_user(user_id: int, request: Request, body: ApproveIn = ApproveIn(), cur=Write):
    t = _target(cur, user_id)
    if t["account_status"] != "Pending":
        raise HTTPException(409, f"Only Pending accounts can be approved (this one is {t['account_status']}).")
    role_id = _role_id(cur, body.role_code) if body.role_code else t["requested_role_id"]
    cur.execute("""UPDATE users SET account_status = 'Active', assigned_role_id = %s, approved_by_user_id = %s,
                          approved_at = now(), updated_at = now() WHERE user_id = %s""",
                (role_id, request.state.user["user_id"], user_id))
    return {"user_id": user_id, "status": "Active"}


@admin.post("/users/{user_id}/reject")
def reject_user(user_id: int, cur=Write):
    t = _target(cur, user_id)
    if t["account_status"] != "Pending":
        raise HTTPException(409, f"Only Pending accounts can be rejected (this one is {t['account_status']}).")
    cur.execute("UPDATE users SET account_status = 'Rejected', updated_at = now() WHERE user_id = %s", (user_id,))
    return {"user_id": user_id, "status": "Rejected"}


@admin.post("/users/{user_id}/disable")
def disable_user(user_id: int, request: Request, cur=Write):
    t = _target(cur, user_id)
    if user_id == request.state.user["user_id"]:
        raise HTTPException(409, "You cannot disable your own account.")
    if t["account_status"] != "Active":
        raise HTTPException(409, "Only Active accounts can be disabled.")
    if t["role_code"] == "ADMIN" and _other_active_admins(cur, user_id) == 0:
        raise HTTPException(409, "At least one active administrator must remain.")
    cur.execute("UPDATE users SET account_status = 'Disabled', updated_at = now() WHERE user_id = %s", (user_id,))
    return {"user_id": user_id, "status": "Disabled"}


@admin.post("/users/{user_id}/enable")
def enable_user(user_id: int, cur=Write):
    t = _target(cur, user_id)
    if t["account_status"] != "Disabled":
        raise HTTPException(409, "Only Disabled accounts can be enabled.")
    if not t["assigned_role_id"] or not (t["password_hash"] or "").startswith("$2"):
        raise HTTPException(409, "This account has no role or no login credentials (for example a seeded demo account).")
    cur.execute("UPDATE users SET account_status = 'Active', updated_at = now() WHERE user_id = %s", (user_id,))
    return {"user_id": user_id, "status": "Active"}


@admin.post("/users/{user_id}/role")
def change_role(user_id: int, body: RoleIn, request: Request, cur=Write):
    t = _target(cur, user_id)
    role_id = _role_id(cur, body.role_code)
    if t["account_status"] != "Active":
        raise HTTPException(409, "Roles can only be changed on Active accounts (approve pending accounts instead).")
    if t["role_code"] == "ADMIN" and body.role_code != "ADMIN":
        if user_id == request.state.user["user_id"]:
            raise HTTPException(409, "You cannot remove your own administrator role.")
        if _other_active_admins(cur, user_id) == 0:
            raise HTTPException(409, "At least one active administrator must remain.")
    cur.execute("UPDATE users SET assigned_role_id = %s, updated_at = now() WHERE user_id = %s", (role_id, user_id))
    return {"user_id": user_id, "role_code": body.role_code}
