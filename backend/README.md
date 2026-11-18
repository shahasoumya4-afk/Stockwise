# Backend API (phase 4: accounts + read-only data)

FastAPI service over the PostgreSQL database. **All data is synthetic.** This phase serves
operational data and simple derived values (reserved/available stock, allocation coverage,
schedule progress) plus explainable shortage-risk calculations. ML forecasts and procurement recommendations are NOT included.

## Setup (Windows PowerShell, from the `backend` folder)

    python -m pip install -r requirements.txt
    copy .env.example .env        # then edit .env and set DB_PASSWORD
    python -m uvicorn app.main:app --reload

Open http://127.0.0.1:8000/docs for interactive API documentation, and
http://127.0.0.1:8000/health to confirm the database connection.

## Endpoints (all GET)

| Path | Purpose |
|---|---|
| /health | API + database check (public) |
| /api/project-categories, /api/warehouses, /api/suppliers | reference data |
| /api/projects?status=Active&project_category_id= | project list (paged) |
| /api/projects/{id} | project detail + requirement versions |
| /api/projects/{id}/requirements | lines: predicted / proposed / approved, allocated, consumed |
| /api/dashboard/summary | active projects only: line coverage, schedule progress, open POs |
| /api/materials, /api/materials/{id} | material master, suppliers, categories that use it |
| /api/rules?project_category_id= | synthetic quantity rules |
| /api/inventory?warehouse_id=&material_id=&below_reorder= | on-hand, reserved, available, reorder point |
| /api/inventory/{id}/transactions | stock movements |
| /api/purchase-orders?open_only=true, /api/purchase-orders/{id} | POs with outstanding quantities |
| /api/risk/shortages?status=&project_id=&buffer_days=&exclude_ok=true | line-level shortage risk for active projects, with an explanation per line |
| /api/risk/summary | per-project risk counts (OK / WATCH / AT_RISK / SHORT) for the dashboard |
| /api/inventory/requirements/{line_id}/options | free stock, safe surplus, later-due temporary borrow options and supplier delivery timing |
| POST /api/inventory/requirements/{line_id}/allocations | allocate free warehouse stock (ADMIN / INVENTORY_MANAGER) |
| POST /api/inventory/transfers, GET /api/inventory/transfers | transfer safe surplus or explicitly borrow from a later-due project requirement; view the audit ledger |
| /api/risk/reorder | stock rows with available <= reorder point, and whether open orders cover them |
| /api/estimates/model | quantity model version, training size, accuracy summary, supported categories and scale ranges |
| /api/estimates/preview?category_code=&scale_level=&scale_value= | estimate materials for a NEW project (not stored or approved) |
| /api/estimates/compare/{project_id} | model estimate vs the approved quantities of an existing project |

### Quantity estimates
Served from `ml/artifacts/quantity_model_v1.json` (pure Python, no scikit-learn needed). Run
`ml/train_quantity_model.py` first; the API re-reads the file when it changes. Furnace upgrades take
`scale_level` (Small/Medium/Large); the others take a positive `scale_value` (metres, equipment
count, kW). Each line has a point estimate and an empirical p10-p90 range; scales outside the
training range are flagged `extrapolated_scale`. Estimates are synthetic and for preview only: nothing is
saved, and a preview is not an approved requirement. `compare` is in-sample for Completed projects
(the model was trained on them) and out-of-sample for Active ones.

### How shortage risk is calculated (see the docstring in `app/risk.py`)
For each active-project line: still needed = approved - consumed; the line's own reservations are
set aside; the rest is covered from free stock (pooled across warehouses), then from open purchase
orders by expected delivery date. Competing lines are served in need-by order so stock and orders
are never counted twice. OK = covered by stock; WATCH = covered if open orders arrive on time;
AT_RISK = covered only by orders arriving after the need-by date; SHORT = part has no stock or order.
`urgency` (overdue / critical / can_order) uses the preferred supplier's lead time. It is an
explainable calculation on synthetic data, not a forecast or a purchasing instruction.

Read endpoints use read-only database transactions. Inventory managers and administrators can allocate free stock, transfer safe surplus, or confirm a temporary borrow from an active project with a later material need-by date. Temporary borrows reduce the donor reservation, may create donor risk, and require replenishment before the donor need-by date. All transfers are audited; physical on-hand stock does not change. Existing databases need migrations/001_project_allocation_transfers.sql before starting this version. Keep .env out of Git.

## Accounts and login
Every `/api` route needs a signed-in, Active user except `/health`, `/api/auth/options`, `/api/auth/signup`
and `/api/auth/login`. Passwords are stored as bcrypt hashes in the `users` table; logins return a signed token
(send it as `Authorization: Bearer <token>`). The user is re-read on every request, so disabling an account
or changing a role takes effect immediately.

1. Set `JWT_SECRET` in `.env` (see `.env.example`), apply migrations/001_project_allocation_transfers.sql to an existing database (preserve its operational data), then create the first administrator (prompts for a password, never prints it):

        python create_admin.py

2. People sign up (`POST /api/auth/signup`): the account is Pending and cannot log in.
3. An administrator approves or rejects it (`/api/admin/users/...`) and can assign a role.
4. Approved users log in (`POST /api/auth/login`, JSON `{email, password}`).

| Path | Who | Purpose |
|---|---|---|
| GET /api/auth/options | public | departments + roles for the signup form |
| POST /api/auth/signup | public | create a Pending account (ADMIN role cannot be requested) |
| POST /api/auth/login | public | JSON login, returns token + user + permissions |
| POST /api/auth/token | public | form login used by the Authorize button in /docs |
| GET /api/auth/me | signed in | current user and permissions |
| GET /api/admin/users?status=Pending | ADMIN | list accounts by status |
| POST /api/admin/users/{id}/approve, /reject, /disable, /enable, /role | ADMIN | manage accounts |

Rules: at least one Active administrator must remain; you cannot disable or demote yourself; 5 failed logins
per email and address lock login for 15 minutes (per server process); passwords need 10+ characters with a
letter and a digit. Roles are placeholders (ADMIN, PROJECT_HEAD, INVENTORY_MANAGER, PROCUREMENT_OFFICER, VIEWER);
in this version every role can read the data and only ADMIN can manage accounts; ADMIN and INVENTORY_MANAGER can allocate and transfer stock. Logout = the client discards its token.
In `/docs`, click Authorize and use your email as the username.


### Inventory assistant

POST /api/assistant/chat with {"question":"..."}. The endpoint uses a lightweight TF-IDF intent classifier and resolves project/material entities against the database. It supports project lists/status/requirements, remaining allocations, stock, shortage risks, open orders, reorder points, and current access rules. It is read-only, does not call an external LLM, and does not retain conversation history. Responses are synthetic and include source table names.
