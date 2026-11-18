"""
Inventory-management prototype API (data endpoints read-only; accounts are the only writes).

All data is SYNTHETIC. Derived values (reserved / available stock, allocation coverage,
schedule progress) are calculated here from the operational tables. No forecasts, risk
alerts or procurement recommendations exist in the database or in this phase.
"""
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from . import db
from .assistant import router as assistant_router
from .inventory_actions import router as inventory_actions_router
from .common import OPEN_PO_STATUSES, STOCK_CTE, SYNTHETIC_NOTICE, paged, resolve_as_of
from .auth import admin as admin_router
from .auth import router as auth_router
from .estimates import router as estimates_router
from .risk import router as risk_router
from .security import authenticate



@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    yield
    db.close_pool()


app = FastAPI(title="Inventory Management Prototype API", version="0.4.0", description=SYNTHETIC_NOTICE, lifespan=lifespan,
              dependencies=[Depends(authenticate)])  # every route needs a signed-in user except the public paths in security.py
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,  # CORS_ORIGINS=* allows any site (acceptable only for this read-only synthetic demo)
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX") or None,  # e.g. https://.*\.lovable\.app
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(risk_router)
app.include_router(estimates_router)
app.include_router(assistant_router)
app.include_router(inventory_actions_router)

@app.get("/", include_in_schema=False)
def root():
    """The bare address has no page of its own: send people to the interactive docs."""
    return RedirectResponse("/docs")


Cursor = Depends(db.get_cursor)
Limit = Query(50, ge=1, le=500)
Offset = Query(0, ge=0)


PROJECT_SELECT = """
SELECT p.project_id, p.project_code, p.name, p.idea_description, p.status,
       pc.project_category_id, pc.name AS category, pc.scale_kind, pc.scale_unit,
       p.scale_level, p.scale_value, p.equipment_count,
       d.name AS department, u.full_name AS project_head, p.start_date, p.end_date
FROM projects p
JOIN project_categories pc ON pc.project_category_id = p.project_category_id
JOIN departments d ON d.department_id = p.department_id
JOIN users u ON u.user_id = p.project_head_user_id
"""


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


# ------------------------------------------------------------------ health
@app.get("/health", tags=["system"])
def health(cur=Cursor):
    cur.execute("SELECT 1 AS ok")
    return {"status": "ok", "database": "connected", "notice": SYNTHETIC_NOTICE}


# ------------------------------------------------------------------ reference data
@app.get("/api/project-categories", tags=["reference"])
def project_categories(cur=Cursor):
    cur.execute("SELECT project_category_id, category_code, name, scale_kind, scale_unit FROM project_categories ORDER BY 1")
    return cur.fetchall()


@app.get("/api/warehouses", tags=["reference"])
def warehouses(cur=Cursor):
    cur.execute("SELECT warehouse_id, warehouse_code, name, location_description FROM warehouses WHERE is_active ORDER BY 1")
    return cur.fetchall()


@app.get("/api/suppliers", tags=["reference"])
def suppliers(cur=Cursor):
    cur.execute("SELECT supplier_id, supplier_code, name FROM suppliers WHERE is_active ORDER BY 1")
    return cur.fetchall()


# ------------------------------------------------------------------ projects
@app.get("/api/projects", tags=["projects"])
def list_projects(
    status: Optional[Literal["Draft", "Active", "Completed"]] = None,
    project_category_id: Optional[int] = None,
    limit: int = Limit, offset: int = Offset, cur=Cursor,
):
    cur.execute(
        f"""SELECT q.*, COUNT(*) OVER() AS _total FROM ({PROJECT_SELECT}) q
            WHERE (%(status)s IS NULL OR q.status = %(status)s)
              AND (%(cat)s IS NULL OR q.project_category_id = %(cat)s)
            ORDER BY q.start_date DESC, q.project_id LIMIT %(limit)s OFFSET %(offset)s""",
        dict(status=status, cat=project_category_id, limit=limit, offset=offset))
    return paged(cur.fetchall(), limit, offset)


@app.get("/api/projects/{project_id}", tags=["projects"])
def get_project(project_id: int, cur=Cursor):
    cur.execute(PROJECT_SELECT + " WHERE p.project_id = %s", (project_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    cur.execute("""SELECT requirement_version_id, version_number, review_status, prediction_method, generated_at, reviewed_at
                   FROM project_requirement_versions WHERE project_id = %s ORDER BY version_number DESC""", (project_id,))
    row["requirement_versions"] = cur.fetchall()
    return row


@app.get("/api/projects/{project_id}/requirements", tags=["projects"])
def project_requirements(project_id: int, cur=Cursor):
    """Lines of the latest Approved requirement version, with allocation and consumption totals.
    predicted = synthetic rule baseline, proposed = project-head edit, approved = reviewed quantity.
    allocated_quantity is the current outstanding reservation after consumption and transfers."""
    cur.execute("SELECT 1 FROM projects WHERE project_id = %s", (project_id,))
    if not cur.fetchone():
        raise HTTPException(404, "Project not found")
    cur.execute("""
        WITH v AS (
            SELECT requirement_version_id, version_number FROM project_requirement_versions
            WHERE project_id = %(p)s AND review_status = 'Approved' ORDER BY version_number DESC LIMIT 1
        ), consumed_alloc AS (
            SELECT allocation_id, -SUM(quantity_delta) AS consumed FROM inventory_transactions
            WHERE transaction_type = 'Consumption' GROUP BY allocation_id
        ), alloc AS (
            SELECT a.requirement_line_id,
                   SUM(GREATEST(0, a.allocated_quantity - a.transferred_out_quantity - COALESCE(c.consumed, 0))) AS allocated
            FROM inventory_allocations a
            LEFT JOIN consumed_alloc c USING (allocation_id)
            WHERE a.allocation_status = 'Active'
            GROUP BY a.requirement_line_id
        ), cons AS (
            SELECT requirement_line_id, -SUM(quantity_delta) AS consumed FROM inventory_transactions
            WHERE transaction_type = 'Consumption' AND project_id = %(p)s GROUP BY requirement_line_id
        )
        SELECT r.requirement_line_id, r.line_number, m.material_id, m.material_code, m.name AS material_name, u.uom_code,
               r.predicted_quantity, r.proposed_quantity, r.approved_quantity, r.need_by_date,
               COALESCE(a.allocated, 0) AS allocated_quantity,
               COALESCE(c.consumed, 0) AS consumed_quantity,
               GREATEST(0, r.approved_quantity - COALESCE(c.consumed, 0) - COALESCE(a.allocated, 0)) AS unallocated_quantity
        FROM project_material_requirements r
        JOIN v ON v.requirement_version_id = r.requirement_version_id
        JOIN materials m ON m.material_id = r.material_id
        JOIN units_of_measure u ON u.uom_id = m.base_uom_id
        LEFT JOIN alloc a ON a.requirement_line_id = r.requirement_line_id
        LEFT JOIN cons c ON c.requirement_line_id = r.requirement_line_id
        ORDER BY r.line_number""", dict(p=project_id))
    return {"project_id": project_id, "notice": SYNTHETIC_NOTICE, "lines": cur.fetchall()}


# ------------------------------------------------------------------ dashboard
@app.get("/api/dashboard/summary", tags=["dashboard"])
def dashboard_summary(as_of: Optional[date] = None, cur=Cursor):
    """Active projects only. Counts are facts from the data, not risk alerts or forecasts."""
    as_of = resolve_as_of(as_of)
    cur.execute("""
        WITH consumed_alloc AS (
            SELECT allocation_id, -SUM(quantity_delta) AS consumed FROM inventory_transactions
            WHERE transaction_type = 'Consumption' GROUP BY allocation_id
        ), alloc AS (
            SELECT a.requirement_line_id,
                   SUM(GREATEST(0, a.allocated_quantity - a.transferred_out_quantity - COALESCE(c.consumed, 0))) AS allocated
            FROM inventory_allocations a
            LEFT JOIN consumed_alloc c USING (allocation_id)
            WHERE a.allocation_status = 'Active'
            GROUP BY a.requirement_line_id
        ), cons AS (
            SELECT requirement_line_id, -SUM(quantity_delta) AS consumed
            FROM inventory_transactions WHERE transaction_type = 'Consumption' GROUP BY requirement_line_id
        ), lines AS (
            SELECT v.project_id, r.requirement_line_id, r.approved_quantity,
                   COALESCE(a.allocated, 0) AS allocated, COALESCE(c.consumed, 0) AS consumed
            FROM project_requirement_versions v
            JOIN project_material_requirements r ON r.requirement_version_id = v.requirement_version_id
            LEFT JOIN alloc a ON a.requirement_line_id = r.requirement_line_id
            LEFT JOIN cons c ON c.requirement_line_id = r.requirement_line_id
            WHERE v.review_status = 'Approved'
        )
        SELECT p.project_id, p.project_code, p.name, pc.name AS category, p.start_date, p.end_date,
               COUNT(l.requirement_line_id) AS requirement_lines,
               COUNT(*) FILTER (WHERE l.allocated + l.consumed >= l.approved_quantity) AS fully_allocated_lines,
               COUNT(*) FILTER (WHERE l.allocated + l.consumed < l.approved_quantity) AS lines_not_fully_allocated
        FROM projects p
        JOIN project_categories pc ON pc.project_category_id = p.project_category_id
        LEFT JOIN lines l ON l.project_id = p.project_id
        WHERE p.status = 'Active'
        GROUP BY p.project_id, pc.name ORDER BY p.start_date""")
    projects = cur.fetchall()
    for p in projects:
        span = max(1, (p["end_date"] - p["start_date"]).days)
        p["schedule_progress_pct"] = round(min(1.0, max(0.0, (as_of - p["start_date"]).days / span)) * 100, 1)
        p["days_remaining"] = (p["end_date"] - as_of).days
    cur.execute(STOCK_CTE + "SELECT COUNT(*) AS n FROM stock WHERE available_quantity <= reorder_point_quantity")
    below = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) AS n FROM purchase_orders WHERE status = ANY(%s)", (list(OPEN_PO_STATUSES),))
    open_pos = cur.fetchone()["n"]
    return {"as_of": as_of, "notice": SYNTHETIC_NOTICE, "active_project_count": len(projects),
            "open_purchase_orders": open_pos, "stock_rows_available_at_or_below_reorder_point": below,
            "active_projects": projects}


# ------------------------------------------------------------------ materials / rules
@app.get("/api/materials", tags=["materials"])
def list_materials(q: Optional[str] = Query(None, description="search code or name"),
                   material_category_id: Optional[int] = None, limit: int = Limit, offset: int = Offset, cur=Cursor):
    cur.execute("""
        SELECT m.material_id, m.material_code, m.name, mc.name AS material_category, u.uom_code,
               COUNT(*) OVER() AS _total
        FROM materials m
        JOIN material_categories mc ON mc.material_category_id = m.material_category_id
        JOIN units_of_measure u ON u.uom_id = m.base_uom_id
        WHERE m.is_active AND (%(q)s IS NULL OR m.name ILIKE '%%' || %(q)s || '%%' OR m.material_code ILIKE '%%' || %(q)s || '%%')
          AND (%(mc)s IS NULL OR m.material_category_id = %(mc)s)
        ORDER BY m.material_id LIMIT %(limit)s OFFSET %(offset)s""",
        dict(q=q, mc=material_category_id, limit=limit, offset=offset))
    return paged(cur.fetchall(), limit, offset)


@app.get("/api/materials/{material_id}", tags=["materials"])
def get_material(material_id: int, cur=Cursor):
    cur.execute("""SELECT m.material_id, m.material_code, m.name, m.description, mc.name AS material_category, u.uom_code
                   FROM materials m JOIN material_categories mc ON mc.material_category_id = m.material_category_id
                   JOIN units_of_measure u ON u.uom_id = m.base_uom_id WHERE m.material_id = %s""", (material_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Material not found")
    cur.execute("""SELECT DISTINCT pc.project_category_id, pc.name FROM project_category_material_rules r
                   JOIN project_categories pc ON pc.project_category_id = r.project_category_id
                   WHERE r.material_id = %s AND r.is_active ORDER BY 1""", (material_id,))
    row["used_in_project_categories"] = cur.fetchall()
    cur.execute("""SELECT s.supplier_id, s.name AS supplier, ms.supplier_item_code, ms.lead_time_days,
                          ms.minimum_order_quantity, ms.unit_price, ms.currency_code, ms.is_preferred
                   FROM material_suppliers ms JOIN suppliers s ON s.supplier_id = ms.supplier_id
                   WHERE ms.material_id = %s ORDER BY ms.is_preferred DESC, s.supplier_id""", (material_id,))
    row["suppliers"] = cur.fetchall()
    return row


@app.get("/api/rules", tags=["materials"])
def list_rules(project_category_id: Optional[int] = None, cur=Cursor):
    """Synthetic quantity rules (assumptions, not real usage rates)."""
    cur.execute("""SELECT r.rule_id, r.project_category_id, pc.name AS project_category, m.material_code, m.name AS material_name,
                          r.scale_band, r.base_quantity, r.quantity_per_scale_unit, r.rule_version
                   FROM project_category_material_rules r
                   JOIN project_categories pc ON pc.project_category_id = r.project_category_id
                   JOIN materials m ON m.material_id = r.material_id
                   WHERE r.is_active AND (%(c)s IS NULL OR r.project_category_id = %(c)s)
                   ORDER BY r.project_category_id, r.material_id, r.scale_band""", dict(c=project_category_id))
    return {"notice": SYNTHETIC_NOTICE, "rules": cur.fetchall()}


# ------------------------------------------------------------------ inventory
@app.get("/api/inventory", tags=["inventory"])
def list_inventory(warehouse_id: Optional[int] = None, material_id: Optional[int] = None,
                   below_reorder: Optional[bool] = Query(None, description="available <= reorder point (excludes stock on order)"),
                   limit: int = Limit, offset: int = Offset, cur=Cursor):
    cur.execute(STOCK_CTE + """
        SELECT s.*, (s.available_quantity <= s.reorder_point_quantity) AS available_at_or_below_reorder_point,
               COUNT(*) OVER() AS _total
        FROM stock s
        WHERE (%(w)s IS NULL OR s.warehouse_id = %(w)s) AND (%(m)s IS NULL OR s.material_id = %(m)s)
          AND (%(b)s IS NULL OR (s.available_quantity <= s.reorder_point_quantity) = %(b)s)
        ORDER BY s.available_quantity - s.reorder_point_quantity, s.inventory_id
        LIMIT %(limit)s OFFSET %(offset)s""",
        dict(w=warehouse_id, m=material_id, b=below_reorder, limit=limit, offset=offset))
    return paged(cur.fetchall(), limit, offset)


@app.get("/api/inventory/{inventory_id}/transactions", tags=["inventory"])
def inventory_transactions(inventory_id: int, limit: int = Limit, offset: int = Offset, cur=Cursor):
    cur.execute("SELECT 1 FROM inventory WHERE inventory_id = %s", (inventory_id,))
    if not cur.fetchone():
        raise HTTPException(404, "Inventory row not found")
    cur.execute("""SELECT inventory_transaction_id, transaction_type, quantity_delta, occurred_at, project_id,
                          allocation_id, purchase_order_line_id, reference_code, COUNT(*) OVER() AS _total
                   FROM inventory_transactions WHERE inventory_id = %(i)s
                   ORDER BY occurred_at DESC, inventory_transaction_id DESC LIMIT %(limit)s OFFSET %(offset)s""",
                dict(i=inventory_id, limit=limit, offset=offset))
    return paged(cur.fetchall(), limit, offset)


# ------------------------------------------------------------------ purchase orders
@app.get("/api/purchase-orders", tags=["purchase orders"])
def list_purchase_orders(status: Optional[Literal["Ordered", "Partially Received", "Received"]] = None,
                         open_only: bool = False, limit: int = Limit, offset: int = Offset, cur=Cursor):
    cur.execute("""
        SELECT po.purchase_order_id, po.po_number, s.name AS supplier, w.name AS warehouse, po.order_date,
               po.expected_delivery_date, po.actual_delivery_date, po.status, COUNT(*) OVER() AS _total
        FROM purchase_orders po
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        JOIN warehouses w ON w.warehouse_id = po.warehouse_id
        WHERE (%(status)s IS NULL OR po.status = %(status)s)
          AND (NOT %(open)s OR po.status = ANY(%(open_list)s))
        ORDER BY po.order_date DESC, po.purchase_order_id DESC LIMIT %(limit)s OFFSET %(offset)s""",
        dict(status=status, open=open_only, open_list=list(OPEN_PO_STATUSES), limit=limit, offset=offset))
    return paged(cur.fetchall(), limit, offset)


@app.get("/api/purchase-orders/{purchase_order_id}", tags=["purchase orders"])
def get_purchase_order(purchase_order_id: int, cur=Cursor):
    cur.execute("""SELECT po.purchase_order_id, po.po_number, s.name AS supplier, w.name AS warehouse, po.order_date,
                          po.expected_delivery_date, po.actual_delivery_date, po.status
                   FROM purchase_orders po JOIN suppliers s ON s.supplier_id = po.supplier_id
                   JOIN warehouses w ON w.warehouse_id = po.warehouse_id WHERE po.purchase_order_id = %s""", (purchase_order_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Purchase order not found")
    cur.execute("""SELECT l.purchase_order_line_id, l.line_number, m.material_code, m.name AS material_name, u.uom_code,
                          l.ordered_quantity, l.received_quantity, l.ordered_quantity - l.received_quantity AS outstanding_quantity,
                          l.unit_price, l.expected_delivery_date
                   FROM purchase_order_lines l JOIN materials m ON m.material_id = l.material_id
                   JOIN units_of_measure u ON u.uom_id = m.base_uom_id
                   WHERE l.purchase_order_id = %s ORDER BY l.line_number""", (purchase_order_id,))
    row["lines"] = cur.fetchall()
    return row
