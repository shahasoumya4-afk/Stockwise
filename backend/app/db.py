"""PostgreSQL connection pool. Connections are read-only except get_write_cursor (accounts only).

Configuration (environment variables or backend/.env):
  DATABASE_URL        full connection string (cloud hosts). If set, the DB_* variables are ignored.
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD   used when DATABASE_URL is not set.
  DB_POOL_MAX         maximum pooled connections (default 10)

Read-only mode uses a per-transaction setting (psycopg2 `readonly`), which also works behind
connection poolers that reject startup options.
"""
import os

import psycopg2
from dotenv import load_dotenv
from fastapi import HTTPException
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

load_dotenv()
_pool: ThreadedConnectionPool | None = None


def init_pool() -> None:
    global _pool
    maxconn = int(os.getenv("DB_POOL_MAX", "10"))
    url = os.getenv("DATABASE_URL")
    if url:
        _pool = ThreadedConnectionPool(1, maxconn, dsn=url)
    else:
        _pool = ThreadedConnectionPool(
            1, maxconn,
            host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "inventory_db"), user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD") or os.getenv("PGPASSWORD"))


def close_pool() -> None:
    if _pool is not None:
        _pool.closeall()


def _checkout(readonly: bool = True):
    """Get a healthy connection (cloud databases may close idle connections); read-only unless asked."""
    for _ in range(3):
        conn = _pool.getconn()
        try:
            conn.rollback()
            conn.readonly = readonly
            with conn.cursor() as c:
                c.execute("SELECT 1")
            conn.rollback()
            return conn
        except Exception:
            _pool.putconn(conn, close=True)
    raise HTTPException(503, "Database unavailable")


def get_cursor():
    """FastAPI dependency: yields a dict cursor and always returns the connection to the pool."""
    conn = _checkout()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
    finally:
        try:
            conn.rollback()
        finally:
            _pool.putconn(conn)


def get_write_cursor():
    """FastAPI dependency for the few endpoints that change data (signup, user administration).
    Commits when the request succeeds and rolls back on any error."""
    conn = _checkout(readonly=False)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            conn.rollback()
        finally:
            _pool.putconn(conn)
