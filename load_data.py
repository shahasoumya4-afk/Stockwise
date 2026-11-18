#!/usr/bin/env python3
"""
load_data.py - create the SYNTHETIC prototype tables in PostgreSQL and import the generated CSVs.

Install:   pip install psycopg2-binary
Run:       python load_data.py --dbname inventory_db --user postgres
           python load_data.py --database-url "postgresql://user:pass@host/db?sslmode=require"
           (password is read from the PGPASSWORD env var, or prompted)
Re-run:    add --reset to drop and recreate the tables first.
"""
import argparse
import getpass
import json
import os
import sys
from pathlib import Path

import psycopg2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                    help="full connection string (cloud databases); overrides --host/--port/--dbname/--user")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", default="5432")
    ap.add_argument("--dbname")
    ap.add_argument("--user", default="postgres")
    ap.add_argument("--data-dir", default="data/generated/v1")
    ap.add_argument("--schema", default="schema.sql")
    ap.add_argument("--reset", action="store_true", help="drop existing tables first")
    a = ap.parse_args()

    data_dir = Path(a.data_dir)
    manifest = json.loads((data_dir / "generation_manifest.json").read_text(encoding="utf-8"))
    order = manifest["import_order"]
    if a.database_url:
        conn = psycopg2.connect(a.database_url)
    else:
        if not a.dbname:
            sys.exit("Provide --dbname (local database) or --database-url (cloud database).")
        password = os.environ.get("PGPASSWORD") or getpass.getpass(f"Password for {a.user}: ")
        conn = psycopg2.connect(host=a.host, port=a.port, dbname=a.dbname, user=a.user, password=password)
    try:
        with conn, conn.cursor() as cur:  # one transaction: all-or-nothing
            if a.reset:
                for t in reversed(order):
                    cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
            cur.execute(Path(a.schema).read_text(encoding="utf-8"))
            for t in order:
                cols = ", ".join(c["name"] for c in manifest["tables"][t]["columns"])
                with open(data_dir / f"{t}.csv", "r", encoding="utf-8", newline="") as fh:
                    cur.copy_expert(f"COPY {t} ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true)", fh)
                pk = manifest["tables"][t]["columns"][0]["name"]  # keep the id sequence ahead of the loaded rows
                cur.execute(f"SELECT setval(pg_get_serial_sequence('{t}', '{pk}'), COALESCE((SELECT MAX({pk}) FROM {t}), 0) + 1, false)")
                cur.execute(f"SELECT count(*) FROM {t}")
                n, expected = cur.fetchone()[0], manifest["tables"][t]["row_count"]
                print(f"  {t:<34}{n:>7}  {'OK' if n == expected else 'MISMATCH (expected %d)' % expected}")
                if n != expected:
                    raise SystemExit("Row count mismatch - rolled back.")
        print("Done. All tables created and loaded (synthetic data).")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
