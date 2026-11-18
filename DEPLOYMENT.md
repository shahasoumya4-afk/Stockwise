# Deploying the backend + database to the cloud (permanent link for the dashboard)

All data is SYNTHETIC. Data endpoints are read-only and require a signed-in user; accounts are the only writes.
Hosting plans and free-tier limits change, so check each provider's current terms before relying
on them. Examples below use Render for the API (Docker) and any managed PostgreSQL (Render,
Neon, Supabase, Railway...).

## What you need
- A GitHub account and this project in a GitHub repository.
- A managed PostgreSQL database that accepts connections from your laptop (all of the above do).

## 1. Put the project on GitHub
Commit everything except secrets and generated data. The root `.gitignore` already excludes
`.env`, `.venv/`, `data/` and `__pycache__/`. **`ml/artifacts/quantity_model_v1.json` must be committed**
(the API image copies it). Never commit `backend/.env` or any connection string.

    git init
    git add .
    git commit -m "Synthetic inventory prototype"
    (create an empty repository on github.com, then follow its "push an existing repository" commands)

## 2. Create the cloud database
Create a PostgreSQL database with your provider and copy its EXTERNAL connection string, which
looks like `postgresql://user:password@host:5432/dbname?sslmode=require`. Treat it like a password.

## 3. Load the data from your laptop
Run from the project root. Use the stress data for the demo, or `data/generated/v1` for the baseline.

    python load_data.py --database-url "PASTE_CONNECTION_STRING" --data-dir data/generated/v1_stress --reset

Every table should show OK, then `Done.` (Add the `--reset` flag only when you intend to recreate the tables.)

## 3b. Create the first administrator in the cloud database
From the `backend` folder, point the script at the cloud database (PowerShell shown) and run it. It asks for a password
and never prints it:

    $env:DATABASE_URL = "PASTE_CONNECTION_STRING"
    python create_admin.py

Do this once, after the data load. Re-running `load_data.py --reset` wipes all accounts, so never use `--reset` after real users exist.

## 4. Create the API service (Render example)
New > Web Service > connect the GitHub repository, then:
- Runtime / language: Docker. Dockerfile path: `./Dockerfile` (the repository root is the build context).
- Instance type: Free (it sleeps after about 15 minutes idle; the first request after that can take up to a minute).
- Health check path: `/health`
- Environment variables:

| Name | Value |
|---|---|
| DATABASE_URL | the connection string from step 2 (the provider's internal URL also works if both are on the same provider) |
| JWT_SECRET | a long random string: `python -c "import secrets; print(secrets.token_urlsafe(48))"` (never reuse your local one, never commit it) |
| AS_OF_DATE | 2026-10-30 (keeps the risk calculations aligned with the generated data) |
| CORS_ORIGIN_REGEX | `https://.*\.lovable\.app` (adjust if your Lovable app uses another domain) |
| CORS_ORIGINS | `http://localhost:5173,http://localhost:3000` (optional, for local front-end work) |

## 5. Check it
Open `https://YOUR-SERVICE.onrender.com/health` (public), then `/docs`. Click Authorize and log in with the administrator
you created, then try `/api/risk/summary` (stress data: OK 88, WATCH 10, AT_RISK 2, SHORT 2).

## 6. Point the dashboard at it
In Lovable set `VITE_API_BASE_URL` to `https://YOUR-SERVICE.onrender.com` (no trailing slash).
The dashboard logs in through `/api/auth/login`. If the browser reports a CORS error, copy the exact app address from the address bar and add it to
`CORS_ORIGINS` (or widen `CORS_ORIGIN_REGEX`), then redeploy.

## Notes and limits
- Cold starts: show a loading state in the dashboard; the first call after idle time is slow.
- Free databases can have size or expiry limits. If one expires, create a new database and repeat step 3.
- Accounts are real: use strong passwords, keep `JWT_SECRET` and the database URL private, and only approve people you know.
  Signup is open to anyone with the link but accounts stay Pending until an administrator approves them. Do not store
  anything real in this prototype. Throttling is per server process, and tokens last 8 hours by default.
- If a connection string is ever exposed, rotate the database password with your provider.
- Changing the model: retrain with `ml/train_quantity_model.py`, commit the new JSON, and redeploy.
