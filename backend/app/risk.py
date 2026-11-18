"""
Shortage-risk logic (read-only). All data is SYNTHETIC.

For every requirement line of an ACTIVE project that still needs material, the calculation asks:

    still needed      = approved quantity - consumed so far
    already reserved  = this line's own outstanding allocations (already earmarked, not at risk)
    uncovered         = still needed - already reserved

and then covers the uncovered quantity, in this order, from a shared pool per material:
    1. free stock   (on-hand minus ALL reservations, summed over warehouses - pooled, see assumptions)
    2. open purchase-order quantity (ordered - received), earliest expected delivery first

Competing demands for the same material are served in need-by-date order, so two projects cannot
both "use" the same free stock or the same incoming order.

Status (per line):
    OK       nothing uncovered, or fully covered by free stock
    WATCH    fully covered, but only if open orders arrive on time (on or before need-by minus buffer)
    AT_RISK  fully covered only if some open orders arrive LATE (after need-by minus buffer)
    SHORT    part of the requirement has no stock and no open order behind it
Urgency (only when a gap or late supply exists), based on the preferred supplier's lead time:
    overdue   need-by date already passed
    critical  latest order date has passed (a new order could not arrive by need-by)
    can_order a new order placed by `latest_order_date` could still arrive in time

Assumptions: warehouses are pooled (stock can be moved between them); open orders arrive on their
expected dates (overdue orders are treated as arriving today); lead time = preferred supplier's.
This is an explainable calculation on synthetic data, not a forecast or a purchasing instruction.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query

from . import db
from .common import OPEN_PO_STATUSES, STOCK_CTE, SYNTHETIC_NOTICE, resolve_as_of

router = APIRouter(prefix="/api/risk", tags=["risk"])
ZERO = Decimal("0")
STATUS_RANK = {"OK": 0, "WATCH": 1, "AT_RISK": 2, "SHORT": 3}


def _fmt(q) -> str:
    q = Decimal(q)
    return f"{q:,.0f}" if q == q.to_integral_value() else f"{q:,.1f}"


def evaluate(lines: list, free_stock: dict, po_supply: dict, as_of: date, buffer_days: int = 0) -> list:
    """Pure function (no database): returns one result dict per line that still needs material."""
    pool = {m: Decimal(q) for m, q in free_stock.items()}
    supply = {m: [dict(s, qty=Decimal(s["qty"])) for s in sorted(lst, key=lambda x: x["date"])] for m, lst in po_supply.items()}
    results = []
    for ln in sorted(lines, key=lambda l: (l["need_by_date"], l["project_id"], l["line_number"])):
        approved, consumed, reserved = Decimal(ln["approved_quantity"]), Decimal(ln["consumed_quantity"]), Decimal(ln["reserved_quantity"])
        needed = max(ZERO, approved - consumed)
        if needed <= ZERO:
            continue  # fully consumed
        uom = uom_u = ln["uom_code"]
        m = ln["material_id"]
        uncovered = max(ZERO, needed - reserved)
        from_stock = min(uncovered, pool.get(m, ZERO))
        pool[m] = pool.get(m, ZERO) - from_stock
        gap = uncovered - from_stock
        deadline = ln["need_by_date"] - timedelta(days=buffer_days)
        on_time = late = ZERO
        used = []
        for s in supply.get(m, []):
            if gap <= ZERO:
                break
            if s["qty"] <= ZERO:
                continue
            take = min(gap, s["qty"])
            s["qty"] -= take
            gap -= take
            arrives = max(s["date"], as_of)
            is_late = arrives > deadline
            on_time, late = (on_time, late + take) if is_late else (on_time + take, late)
            used.append({"po_number": s["po_number"], "quantity": take, "expected_delivery_date": s["date"], "late": is_late,
                         "overdue_order": s["date"] < as_of})
        short = gap
        if uncovered <= ZERO or from_stock == uncovered:
            status = "OK"
        elif short > ZERO:
            status = "SHORT"
        elif late > ZERO:
            status = "AT_RISK"
        else:
            status = "WATCH"
        lead = ln.get("lead_time_days")
        latest_order = ln["need_by_date"] - timedelta(days=int(lead)) if lead else None
        urgency = None
        if status in ("SHORT", "AT_RISK"):
            if ln["need_by_date"] < as_of:
                urgency = "overdue"
            elif latest_order is not None and latest_order < as_of:
                urgency = "critical"
            else:
                urgency = "can_order"
        parts = [f"Needs {_fmt(needed)} {uom_u} more"]
        if reserved > ZERO:
            parts.append(f"{_fmt(min(reserved, needed))} already reserved for this line")
        if uncovered > ZERO:
            parts.append(f"{_fmt(from_stock)} from free stock")
            if on_time > ZERO:
                parts.append(f"{_fmt(on_time)} from open orders arriving by need-by date")
            if late > ZERO:
                parts.append(f"{_fmt(late)} from open orders arriving AFTER need-by date")
            if short > ZERO:
                parts.append(f"{_fmt(short)} not covered by stock or open orders")
        results.append({
            "requirement_line_id": ln["requirement_line_id"], "project_id": ln["project_id"], "project_code": ln["project_code"],
            "project_name": ln["project_name"], "material_id": m, "material_code": ln["material_code"],
            "material_name": ln["material_name"], "uom_code": uom, "need_by_date": ln["need_by_date"],
            "days_until_need": (ln["need_by_date"] - as_of).days, "approved_quantity": approved, "consumed_quantity": consumed,
            "still_needed": needed, "reserved_for_line": min(reserved, needed), "uncovered_quantity": uncovered,
            "covered_by_free_stock": from_stock, "covered_by_on_time_orders": on_time, "covered_by_late_orders": late,
            "not_covered": short, "status": status, "urgency": urgency, "lead_time_days": lead,
            "latest_order_date": latest_order if status in ("SHORT", "AT_RISK") else None,
            "orders_used": used, "explanation": "; ".join(parts) + "."})
    return results


LINES_SQL = """
WITH cons AS (
    SELECT requirement_line_id, -SUM(quantity_delta) AS consumed FROM inventory_transactions
    WHERE transaction_type = 'Consumption' GROUP BY requirement_line_id
), consumed_alloc AS (
    SELECT allocation_id, -SUM(quantity_delta) AS consumed FROM inventory_transactions
    WHERE transaction_type = 'Consumption' GROUP BY allocation_id
), reserved AS (
    SELECT a.requirement_line_id, SUM(a.allocated_quantity - a.transferred_out_quantity - COALESCE(c.consumed, 0)) AS reserved
    FROM inventory_allocations a LEFT JOIN consumed_alloc c ON c.allocation_id = a.allocation_id
    WHERE a.allocation_status = 'Active' GROUP BY a.requirement_line_id
)
SELECT r.requirement_line_id, r.line_number, p.project_id, p.project_code, p.name AS project_name,
       m.material_id, m.material_code, m.name AS material_name, u.uom_code, r.approved_quantity,
       COALESCE(c.consumed, 0) AS consumed_quantity, COALESCE(rs.reserved, 0) AS reserved_quantity,
       r.need_by_date, pref.lead_time_days
FROM projects p
JOIN project_requirement_versions v ON v.project_id = p.project_id AND v.review_status = 'Approved'
     AND v.version_number = (SELECT MAX(v2.version_number) FROM project_requirement_versions v2
                             WHERE v2.project_id = p.project_id AND v2.review_status = 'Approved')
JOIN project_material_requirements r ON r.requirement_version_id = v.requirement_version_id
JOIN materials m ON m.material_id = r.material_id
JOIN units_of_measure u ON u.uom_id = m.base_uom_id
LEFT JOIN cons c ON c.requirement_line_id = r.requirement_line_id
LEFT JOIN reserved rs ON rs.requirement_line_id = r.requirement_line_id
LEFT JOIN material_suppliers pref ON pref.material_id = m.material_id AND pref.is_preferred
WHERE p.status = 'Active'
"""


def compute_risk(cur, as_of: date, buffer_days: int) -> list:
    cur.execute(LINES_SQL)
    lines = cur.fetchall()
    cur.execute(STOCK_CTE + "SELECT material_id, SUM(GREATEST(available_quantity, 0)) AS free FROM stock GROUP BY material_id")
    free = {r["material_id"]: r["free"] for r in cur.fetchall()}
    cur.execute("""SELECT l.material_id, po.po_number, l.expected_delivery_date AS date,
                          l.ordered_quantity - l.received_quantity AS qty
                   FROM purchase_order_lines l JOIN purchase_orders po ON po.purchase_order_id = l.purchase_order_id
                   WHERE po.status = ANY(%s) AND l.ordered_quantity > l.received_quantity""", (list(OPEN_PO_STATUSES),))
    supply = {}
    for r in cur.fetchall():
        supply.setdefault(r["material_id"], []).append({"po_number": r["po_number"], "date": r["date"], "qty": r["qty"]})
    return evaluate(lines, free, supply, as_of, buffer_days)


Cursor = Depends(db.get_cursor)
StatusFilter = Query(None, pattern="^(OK|WATCH|AT_RISK|SHORT)$")


@router.get("/shortages")
def shortages(as_of: Optional[date] = None, buffer_days: int = Query(0, ge=0, le=60, description="safety margin before need-by"),
              status: Optional[str] = StatusFilter, project_id: Optional[int] = None, material_id: Optional[int] = None,
              exclude_ok: bool = Query(False, description="hide lines with status OK"), cur=Cursor):
    """Explainable line-level shortage risk for ACTIVE projects (worst first)."""
    as_of = resolve_as_of(as_of)
    rows = compute_risk(cur, as_of, buffer_days)
    rows = [r for r in rows if (status is None or r["status"] == status) and (project_id is None or r["project_id"] == project_id)
            and (material_id is None or r["material_id"] == material_id) and not (exclude_ok and r["status"] == "OK")]
    rows.sort(key=lambda r: (-STATUS_RANK[r["status"]], r["need_by_date"], r["project_id"]))
    return {"as_of": as_of, "buffer_days": buffer_days, "notice": SYNTHETIC_NOTICE, "total": len(rows), "items": rows}


@router.get("/summary")
def risk_summary(as_of: Optional[date] = None, buffer_days: int = Query(0, ge=0, le=60), cur=Cursor):
    """Per-project risk counts for the dashboard (active projects only)."""
    as_of = resolve_as_of(as_of)
    rows = compute_risk(cur, as_of, buffer_days)
    cur.execute("SELECT project_id, project_code, name FROM projects WHERE status = 'Active' ORDER BY start_date, project_id")
    projects = []
    for p in cur.fetchall():
        mine = [r for r in rows if r["project_id"] == p["project_id"]]
        counts = {k: sum(1 for r in mine if r["status"] == k) for k in STATUS_RANK}
        worst = max(mine, key=lambda r: STATUS_RANK[r["status"]], default=None)
        projects.append({**p, "lines_evaluated": len(mine), "counts": counts,
                         "worst_status": worst["status"] if worst else "OK",
                         "next_need_by_at_risk": min((r["need_by_date"] for r in mine if r["status"] in ("SHORT", "AT_RISK")), default=None)})
    totals = {k: sum(1 for r in rows if r["status"] == k) for k in STATUS_RANK}
    return {"as_of": as_of, "buffer_days": buffer_days, "notice": SYNTHETIC_NOTICE, "totals": totals, "projects": projects}


@router.get("/reorder")
def reorder_points(as_of: Optional[date] = None, cur=Cursor):
    """Stock rows whose AVAILABLE quantity is at or below the reorder point, with open-order cover."""
    as_of = resolve_as_of(as_of)
    cur.execute(STOCK_CTE + """, on_order AS (
            SELECT po.warehouse_id, l.material_id, SUM(l.ordered_quantity - l.received_quantity) AS qty,
                   MIN(l.expected_delivery_date) AS next_expected
            FROM purchase_order_lines l JOIN purchase_orders po ON po.purchase_order_id = l.purchase_order_id
            WHERE po.status = ANY(%s) AND l.ordered_quantity > l.received_quantity GROUP BY po.warehouse_id, l.material_id)
        SELECT s.inventory_id, s.warehouse, s.material_code, s.material_name, s.uom_code, s.on_hand_quantity,
               s.reserved_quantity, s.available_quantity, s.reorder_point_quantity, s.safety_stock_quantity,
               COALESCE(o.qty, 0) AS on_order_quantity, o.next_expected AS next_expected_delivery,
               s.available_quantity + COALESCE(o.qty, 0) AS inventory_position
        FROM stock s LEFT JOIN on_order o ON o.warehouse_id = s.warehouse_id AND o.material_id = s.material_id
        WHERE s.available_quantity <= s.reorder_point_quantity
        ORDER BY s.available_quantity - s.reorder_point_quantity, s.inventory_id""", (list(OPEN_PO_STATUSES),))
    items = cur.fetchall()
    for r in items:
        r["reorder_point_status"] = "ON_ORDER" if r["inventory_position"] > r["reorder_point_quantity"] else "BELOW_REORDER_POINT"
    return {"as_of": as_of, "notice": SYNTHETIC_NOTICE, "total": len(items), "items": items}
