#!/usr/bin/env python3
"""
Create the FIRST administrator account (accounts created through signup are never administrators).

Run from the backend folder, with the same database settings as the API (backend/.env or DATABASE_URL):
    python create_admin.py
You are prompted for the details and a password (not shown). The password is never printed or stored
anywhere except as a bcrypt hash in the users table. For scripts, set ADMIN_PASSWORD in the environment.
"""
import argparse
import getpass
import os
import sys

import psycopg2
from dotenv import load_dotenv

from app.security import hash_password, validate_password

load_dotenv()


def connect():
    url = os.getenv("DATABASE_URL")
    if url:
        return psycopg2.connect(url)
    return psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                            dbname=os.getenv("DB_NAME", "inventory_db"), user=os.getenv("DB_USER", "postgres"),
                            password=os.getenv("DB_PASSWORD") or os.getenv("PGPASSWORD"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full-name")
    ap.add_argument("--email")
    ap.add_argument("--employee-id")
    ap.add_argument("--department-code", help="for example MECH, ELEC, MAINT, PROC, OPS")
    a = ap.parse_args()
    name = a.full_name or input("Full name: ").strip()
    email = (a.email or input("Email: ").strip()).lower()
    emp = a.employee_id or input("Employee ID: ").strip()
    password = os.getenv("ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            sys.exit("Passwords do not match.")
    try:
        validate_password(password)
    except ValueError as e:
        sys.exit(str(e))
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT department_id, department_code, name FROM departments WHERE is_active ORDER BY department_id")
            deps = cur.fetchall()
            code = (a.department_code or "").upper()
            if not code:
                print("Departments: " + ", ".join(f"{c} ({n})" for _, c, n in deps))
                code = input("Department code: ").strip().upper()
            dep = next((d for d in deps if d[1] == code), None)
            if not dep:
                sys.exit(f"Unknown department code '{code}'.")
            cur.execute("SELECT role_id FROM roles WHERE role_code = 'ADMIN'")
            row = cur.fetchone()
            if not row:
                sys.exit("ADMIN role not found. Load the data first (load_data.py).")
            cur.execute("SELECT 1 FROM users WHERE lower(email) = %s OR employee_id = %s", (email, emp))
            if cur.fetchone():
                sys.exit("A user with this email or employee ID already exists.")
            cur.execute("""INSERT INTO users (employee_id, full_name, email, password_hash, department_id, requested_role_id,
                                              assigned_role_id, account_status, approved_at, created_at, updated_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, 'Active', now(), now(), now()) RETURNING user_id""",
                        (emp, name, email, hash_password(password), dep[0], row[0], row[0]))
            print(f"Administrator created (user_id {cur.fetchone()[0]}). You can log in with {email}.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
