"""Actions for allocating free stock and transferring safe project allocation surplus."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import db
from .common import OPEN_PO_STATUSES, STOCK_CTE, SYNTHETIC_NOTICE, paged, resolve_as_of
from .risk import compute_risk

router = APIRouter(tags=["inventory actions"])
ZERO = Decimal("0")
def _fmt(value: Decimal) -> str:
    return format(value.normalize(), "f")

Read = Depends(db.get_cursor)
Write = Depends(db.get_write_cursor)


class AllocateIn(BaseModel):
    warehouse_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    notes: str = Field(default="", max_length=500)


class TransferIn(BaseModel):
    source_allocation_id: int = Field(gt=0)
    target_requirement_line_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    temporary_borrow: bool = False
    notes: str = Field(default="", max_length=500)


def _manager(request: Request) -> int:
    user = getattr(request.state, "user", None)
    if not user or user.get("role_code") not in {"ADMIN", "INVENTORY_MANAGER"}:
        raise HTTPException(403, "Only an administrator or inventory manager can allocate or transfer stock.")
    return int(user["user_id"])


def _line(cur, line_id: int, lock: bool = False) -> dict:
    suffix = " FOR UPDATE OF p, r" if lock else ""
    cur.execute("""
        SELECT r.requirement_line_id, r.approved_quantity, r.need_by_date,
               p.project_id, p.project_code, p.name AS project_name, p.status AS project_status, p.end_date AS project_end_date,
               m.material_id, m.material_code, m.name AS material_name, u.uom_code
        FROM project_material_requirements r
        JOIN project_requirement_versions v ON v.requirement_version_id = r.requirement_version_id
        JOIN projects p ON p.project_id = v.project_id
        JOIN materials m ON m.material_id = r.material_id
        JOIN units_of_measure u ON u.uom_id = m.base_uom_id
        WHERE r.requirement_line_id = %s AND v.review_status = 'Approved'
          AND v.version_number = (
              SELECT MAX(v2.version_number) FROM project_requirement_versions v2
              WHERE v2.project_id = p.project_id AND v2.review_status = 'Approved'
          )
    """ + suffix, (line_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Approved requirement line not found.")
    if row["project_status"] != "Active":
        raise HTTPException(409, "Stock can only be allocated to an active project.")
    return row


def _consumed_line(cur, line_id: int) -> Decimal:
    cur.execute("""SELECT COALESCE(-SUM(quantity_delta), 0) AS quantity
                   FROM inventory_transactions
                   WHERE transaction_type = 'Consumption' AND requirement_line_id = %s""", (line_id,))
    return Decimal(cur.fetchone()["quantity"])


def _reserved_line(cur, line_id: int) -> Decimal:
    cur.execute("""
        SELECT COALESCE(SUM(GREATEST(0, a.allocated_quantity - a.transferred_out_quantity - COALESCE(c.consumed, 0))), 0) AS quantity
        FROM inventory_allocations a
        LEFT JOIN (
            SELECT allocation_id, -SUM(quantity_delta) AS consumed
            FROM inventory_transactions
            WHERE transaction_type = 'Consumption' GROUP BY allocation_id
        ) c USING (allocation_id)
        WHERE a.requirement_line_id = %s AND a.allocation_status = 'Active'
    """, (line_id,))
    return Decimal(cur.fetchone()["quantity"])


def _need(cur, line: dict) -> tuple[Decimal, Decimal, Decimal]:
    consumed = _consumed_line(cur, int(line["requirement_line_id"]))
    reserved = _reserved_line(cur, int(line["requirement_line_id"]))
    needed = max(ZERO, Decimal(line["approved_quantity"]) - consumed - reserved)
    return consumed, reserved, needed


def _free_for_material(cur, material_id: int) -> Decimal:
    cur.execute(STOCK_CTE + """
        SELECT COALESCE(SUM(GREATEST(available_quantity, 0)), 0) AS quantity
        FROM stock WHERE material_id = %s
    """, (material_id,))
    return Decimal(cur.fetchone()["quantity"])


def _free_options(cur, material_id: int, need: Decimal) -> list[dict]:
    cur.execute(STOCK_CTE + """
        SELECT warehouse_id, warehouse, material_code, material_name, uom_code,
               GREATEST(available_quantity, 0) AS available_quantity
        FROM stock
        WHERE material_id = %s AND available_quantity > 0
        ORDER BY available_quantity DESC, warehouse_id
    """, (material_id,))
    result = []
    left = need
    for row in cur.fetchall():
        quantity = min(left, Decimal(row["available_quantity"]))
        if quantity > ZERO:
            result.append({**row, "recommended_quantity": quantity})
            left -= quantity
        if left <= ZERO:
            break
    return result


def _order_options(cur, material_id: int, need_by: date) -> list[dict]:
    cur.execute("""
        SELECT po.po_number, po.status, s.name AS supplier_name, po.warehouse_id,
               l.ordered_quantity - l.received_quantity AS outstanding_quantity,
               l.expected_delivery_date,
               (l.expected_delivery_date <= %s) AS on_time
        FROM purchase_order_lines l
        JOIN purchase_orders po ON po.purchase_order_id = l.purchase_order_id
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        WHERE l.material_id = %s AND po.status = ANY(%s)
          AND l.ordered_quantity > l.received_quantity
        ORDER BY l.expected_delivery_date, po.po_number LIMIT 12
    """, (need_by, material_id, list(OPEN_PO_STATUSES)))
    return cur.fetchall()


def _donor_options(cur, target: dict, target_gap: Decimal) -> list[dict]:
    if target_gap <= ZERO:
        return []
    cur.execute("""
        WITH latest AS (
            SELECT DISTINCT ON (project_id) project_id, requirement_version_id
            FROM project_requirement_versions WHERE review_status = 'Approved'
            ORDER BY project_id, version_number DESC
        ), consumed_line AS (
            SELECT requirement_line_id, -SUM(quantity_delta) AS consumed
            FROM inventory_transactions WHERE transaction_type = 'Consumption'
            GROUP BY requirement_line_id
        ), consumed_allocation AS (
            SELECT allocation_id, -SUM(quantity_delta) AS consumed
            FROM inventory_transactions WHERE transaction_type = 'Consumption'
            GROUP BY allocation_id
        ), allocation_rows AS (
            SELECT a.allocation_id, a.requirement_line_id, a.warehouse_id,
                   GREATEST(0, a.allocated_quantity - a.transferred_out_quantity - COALESCE(c.consumed, 0)) AS row_remaining
            FROM inventory_allocations a
            LEFT JOIN consumed_allocation c USING (allocation_id)
            WHERE a.allocation_status = 'Active'
        ), line_totals AS (
            SELECT requirement_line_id, SUM(row_remaining) AS total_remaining
            FROM allocation_rows GROUP BY requirement_line_id
        )
        SELECT p.project_id AS donor_project_id, p.project_code AS donor_project_code,
               p.name AS donor_project_name, p.end_date AS donor_project_end_date, r.requirement_line_id AS donor_requirement_line_id,
               r.approved_quantity, COALESCE(cl.consumed, 0) AS consumed_quantity,
               ar.allocation_id AS source_allocation_id, ar.warehouse_id, w.name AS warehouse,
               ar.row_remaining, lt.total_remaining, r.need_by_date AS donor_need_by
        FROM allocation_rows ar
        JOIN line_totals lt USING (requirement_line_id)
        JOIN project_material_requirements r ON r.requirement_line_id = ar.requirement_line_id
        JOIN latest v ON v.requirement_version_id = r.requirement_version_id
        JOIN projects p ON p.project_id = v.project_id
        JOIN warehouses w ON w.warehouse_id = ar.warehouse_id
        LEFT JOIN consumed_line cl ON cl.requirement_line_id = r.requirement_line_id
        WHERE p.status = 'Active' AND r.material_id = %s AND r.requirement_line_id <> %s
        ORDER BY p.end_date DESC, p.project_code, r.requirement_line_id, ar.allocation_id
    """, (target["material_id"], target["requirement_line_id"]))
    rows = cur.fetchall()
    options = []
    surplus_left: dict[int, Decimal] = {}
    gap_left = target_gap
    for row in rows:
        donor_line = int(row["donor_requirement_line_id"])
        if donor_line not in surplus_left:
            donor_remaining_need = max(ZERO, Decimal(row["approved_quantity"]) - Decimal(row["consumed_quantity"]))
            surplus_left[donor_line] = max(ZERO, Decimal(row["total_remaining"]) - donor_remaining_need)
        available_surplus = min(Decimal(row["row_remaining"]), surplus_left[donor_line])
        quantity = min(available_surplus, gap_left)
        if quantity > ZERO:
            options.append({
                "donor_project_id": row["donor_project_id"],
                "donor_project_code": row["donor_project_code"],
                "donor_project_name": row["donor_project_name"],
                "donor_requirement_line_id": row["donor_requirement_line_id"],
                "source_allocation_id": row["source_allocation_id"],
                "warehouse_id": row["warehouse_id"],
                "warehouse": row["warehouse"],
                "material_code": target["material_code"],
                "material_name": target["material_name"],
                "uom_code": target["uom_code"],
                "safe_surplus": quantity,
                "recommended_quantity": quantity,
                "donor_need_by": row["donor_need_by"],
                "reason": "This quantity is above the donor project's remaining approved need.",
            })
            surplus_left[donor_line] -= quantity
            gap_left -= quantity
        if gap_left <= ZERO:
            break
    return options


def _scheduled_borrow_options(cur, target: dict, target_gap: Decimal, safe_options: list[dict]) -> list[dict]:
    """Offer later-due project allocations as explicit, replenishment-required temporary loans."""
    if target_gap <= ZERO:
        return []
    safe_by_allocation = {
        int(option["source_allocation_id"]): Decimal(option["recommended_quantity"])
        for option in safe_options
    }
    cur.execute("""
        WITH latest AS (
            SELECT DISTINCT ON (project_id) project_id, requirement_version_id
            FROM project_requirement_versions WHERE review_status = 'Approved'
            ORDER BY project_id, version_number DESC
        ), consumed_line AS (
            SELECT requirement_line_id, -SUM(quantity_delta) AS consumed
            FROM inventory_transactions WHERE transaction_type = 'Consumption'
            GROUP BY requirement_line_id
        ), consumed_allocation AS (
            SELECT allocation_id, -SUM(quantity_delta) AS consumed
            FROM inventory_transactions WHERE transaction_type = 'Consumption'
            GROUP BY allocation_id
        ), allocation_rows AS (
            SELECT a.allocation_id, a.requirement_line_id, a.warehouse_id,
                   GREATEST(0, a.allocated_quantity - a.transferred_out_quantity - COALESCE(c.consumed, 0)) AS row_remaining
            FROM inventory_allocations a
            LEFT JOIN consumed_allocation c USING (allocation_id)
            WHERE a.allocation_status = 'Active'
        ), line_totals AS (
            SELECT requirement_line_id, SUM(row_remaining) AS total_remaining
            FROM allocation_rows GROUP BY requirement_line_id
        )
        SELECT p.project_id AS donor_project_id, p.project_code AS donor_project_code,
               p.name AS donor_project_name, p.end_date AS donor_project_end_date,
               r.requirement_line_id AS donor_requirement_line_id, r.approved_quantity,
               COALESCE(cl.consumed, 0) AS consumed_quantity, r.need_by_date AS donor_need_by,
               ar.allocation_id AS source_allocation_id, ar.warehouse_id, w.name AS warehouse,
               ar.row_remaining, lt.total_remaining
        FROM allocation_rows ar
        JOIN line_totals lt USING (requirement_line_id)
        JOIN project_material_requirements r ON r.requirement_line_id = ar.requirement_line_id
        JOIN latest v ON v.requirement_version_id = r.requirement_version_id
        JOIN projects p ON p.project_id = v.project_id
        JOIN warehouses w ON w.warehouse_id = ar.warehouse_id
        LEFT JOIN consumed_line cl ON cl.requirement_line_id = r.requirement_line_id
        WHERE p.status = 'Active' AND r.material_id = %s
          AND r.requirement_line_id <> %s AND r.need_by_date > %s
        ORDER BY r.need_by_date DESC, p.end_date DESC, p.project_code, ar.allocation_id
    """, (target["material_id"], target["requirement_line_id"], target["need_by_date"]))
    options = []
    surplus_left: dict[int, Decimal] = {}
    gap_left = target_gap
    for row in cur.fetchall():
        donor_line = int(row["donor_requirement_line_id"])
        row_remaining = Decimal(row["row_remaining"])
        if donor_line not in surplus_left:
            donor_need = max(ZERO, Decimal(row["approved_quantity"]) - Decimal(row["consumed_quantity"]))
            line_surplus = max(ZERO, Decimal(row["total_remaining"]) - donor_need)
            surplus_left[donor_line] = line_surplus
        allocation_id = int(row["source_allocation_id"])
        safe_here = min(row_remaining, Decimal(safe_by_allocation.get(allocation_id, ZERO)))
        borrowable = max(ZERO, row_remaining - safe_here)
        # Consume any remaining line-level surplus before exposing quantity that would
        # reduce the donor below its approved remaining requirement.
        surplus_here = min(borrowable, surplus_left[donor_line])
        surplus_left[donor_line] -= surplus_here
        borrowable -= surplus_here
        quantity = min(borrowable, gap_left)
        if quantity > ZERO:
            options.append({
                "donor_project_id": row["donor_project_id"],
                "donor_project_code": row["donor_project_code"],
                "donor_project_name": row["donor_project_name"],
                "donor_project_end_date": row["donor_project_end_date"],
                "donor_requirement_line_id": row["donor_requirement_line_id"],
                "source_allocation_id": row["source_allocation_id"],
                "warehouse_id": row["warehouse_id"],
                "warehouse": row["warehouse"],
                "material_code": target["material_code"],
                "material_name": target["material_name"],
                "uom_code": target["uom_code"],
                "recommended_quantity": quantity,
                "donor_need_by": row["donor_need_by"],
                "days_after_recipient_need": (row["donor_need_by"] - target["need_by_date"]).days,
                "temporary_borrow": True,
                "reason": "This transfer temporarily reduces the donor project's reservation. Replenish it before the donor material need-by date.",
            })
            gap_left -= quantity
        if gap_left <= ZERO:
            break
    return options


@router.get("/api/inventory/requirements/{requirement_line_id}/options", tags=["inventory"])
def fulfillment_options(requirement_line_id: int, cur=Read):
    """Explain available stock, safe donor surplus, and open-order timing for a short requirement."""
    target = _line(cur, requirement_line_id)
    consumed, reserved, needed = _need(cur, target)
    if needed <= ZERO:
        raise HTTPException(409, "This requirement is already fully allocated or consumed.")
    risk = next((r for r in compute_risk(cur, resolve_as_of(None), 0)
                 if int(r["requirement_line_id"]) == requirement_line_id), None)
    if not risk or risk["status"] == "OK":
        raise HTTPException(409, "This requirement is not currently listed as a shortage risk.")
    intervention_gap = Decimal(risk["covered_by_late_orders"]) + Decimal(risk["not_covered"])
    if intervention_gap <= ZERO:
        raise HTTPException(409, "Current stock and on-time orders cover this requirement by its need date.")
    free_options = _free_options(cur, int(target["material_id"]), intervention_gap)
    safe_options = _donor_options(cur, target, intervention_gap)
    safe_quantity = sum((Decimal(option["recommended_quantity"]) for option in safe_options), ZERO)
    borrow_options = _scheduled_borrow_options(cur, target, max(ZERO, intervention_gap - safe_quantity), safe_options)
    return {
        "requirement_line_id": requirement_line_id,
        "project_id": target["project_id"],
        "project_code": target["project_code"],
        "project_name": target["project_name"],
        "material_code": target["material_code"],
        "material_name": target["material_name"],
        "uom_code": target["uom_code"],
        "need_by_date": target["need_by_date"],
        "still_needed": max(ZERO, Decimal(target["approved_quantity"]) - consumed),
        "currently_reserved": reserved,
        "quantity_to_allocate": needed,
        "quantity_to_transfer_for_need_date": intervention_gap,
        "risk_status": risk["status"],
        "free_stock_options": free_options,
        "transfer_options": safe_options,
        "scheduled_borrow_options": borrow_options,
        "open_order_options": _order_options(cur, int(target["material_id"]), target["need_by_date"]),
        "notice": SYNTHETIC_NOTICE,
    }


@router.post("/api/inventory/requirements/{requirement_line_id}/allocations", status_code=201, tags=["inventory"])
def allocate_free_stock(requirement_line_id: int, body: AllocateIn, request: Request, cur=Write):
    user_id = _manager(request)
    target = _line(cur, requirement_line_id, lock=True)
    _, _, needed = _need(cur, target)
    quantity = Decimal(body.quantity)
    if quantity > needed:
        raise HTTPException(409, f"Only {_fmt(needed)} {target['uom_code']} remains to allocate.")
    cur.execute("""
        SELECT i.inventory_id, w.name AS warehouse_name FROM inventory i
        JOIN warehouses w ON w.warehouse_id = i.warehouse_id
        WHERE i.warehouse_id = %s AND i.material_id = %s FOR UPDATE OF i
    """, (body.warehouse_id, target["material_id"]))
    inventory_row = cur.fetchone()
    if not inventory_row:
        raise HTTPException(404, "This material has no inventory row in the selected warehouse.")
    cur.execute(STOCK_CTE + """
        SELECT available_quantity FROM stock
        WHERE warehouse_id = %s AND material_id = %s
    """, (body.warehouse_id, target["material_id"]))
    stock = cur.fetchone()
    available = Decimal(stock["available_quantity"]) if stock else ZERO
    if quantity > available:
        raise HTTPException(409, f"Only {_fmt(max(ZERO, available))} {target['uom_code']} is free in that warehouse. Refresh the options.")
    cur.execute("""
        INSERT INTO inventory_allocations
            (requirement_line_id, warehouse_id, allocated_quantity, transferred_out_quantity,
             allocation_status, allocated_by_user_id, allocated_at, released_at)
        VALUES (%s, %s, %s, 0, 'Active', %s, now(), NULL)
        RETURNING allocation_id
    """, (requirement_line_id, body.warehouse_id, quantity, user_id))
    allocation_id = cur.fetchone()["allocation_id"]
    return {
        "allocation_id": allocation_id,
        "project_id": target["project_id"],
        "project_code": target["project_code"],
        "material_code": target["material_code"],
        "quantity": quantity,
        "warehouse_id": body.warehouse_id,
        "warehouse": inventory_row["warehouse_name"],
        "available_before": available,
        "available_after": available - quantity,
        "message": f"Allocated {_fmt(quantity)} {target['uom_code']} from {inventory_row['warehouse_name']} to {target['project_code']}.",
        "notice": SYNTHETIC_NOTICE,
    }


@router.post("/api/inventory/transfers", status_code=201, tags=["inventory"])
def transfer_project_allocation(body: TransferIn, request: Request, cur=Write):
    user_id = _manager(request)
    cur.execute("SELECT requirement_line_id FROM inventory_allocations WHERE allocation_id = %s", (body.source_allocation_id,))
    source_stub = cur.fetchone()
    if not source_stub:
        raise HTTPException(404, "Source project allocation not found.")
    source_line_id = int(source_stub["requirement_line_id"])
    target_line_id = int(body.target_requirement_line_id)
    if source_line_id == target_line_id:
        raise HTTPException(409, "Source and target must be different project requirement lines.")

    locked: dict[int, dict] = {}
    for line_id in sorted({source_line_id, target_line_id}):
        locked[line_id] = _line(cur, line_id, lock=True)
    source_line, target = locked[source_line_id], locked[target_line_id]
    if int(source_line["project_id"]) == int(target["project_id"]):
        raise HTTPException(409, "A transfer must move allocation between two different projects.")
    if int(source_line["material_id"]) != int(target["material_id"]):
        raise HTTPException(409, "Source and target requirement lines must use the same material.")

    cur.execute("""
        SELECT allocation_id, requirement_line_id, warehouse_id, allocated_quantity,
               transferred_out_quantity, allocation_status
        FROM inventory_allocations WHERE allocation_id = %s FOR UPDATE
    """, (body.source_allocation_id,))
    source_alloc = cur.fetchone()
    if not source_alloc or source_alloc["allocation_status"] != "Active":
        raise HTTPException(409, "The source allocation is no longer active. Refresh transfer options.")

    cur.execute("""
        SELECT i.inventory_id, w.name AS warehouse_name FROM inventory i
        JOIN warehouses w ON w.warehouse_id = i.warehouse_id
        WHERE i.warehouse_id = %s AND i.material_id = %s FOR UPDATE OF i
    """, (source_alloc["warehouse_id"], target["material_id"]))
    if not cur.fetchone():
        raise HTTPException(404, "The source warehouse has no stock row for this material.")

    source_consumed_alloc = ZERO
    cur.execute("""SELECT COALESCE(-SUM(quantity_delta), 0) AS quantity
                   FROM inventory_transactions WHERE transaction_type = 'Consumption' AND allocation_id = %s""",
                (body.source_allocation_id,))
    source_consumed_alloc = Decimal(cur.fetchone()["quantity"])
    source_remaining = max(ZERO, Decimal(source_alloc["allocated_quantity"]) -
                           Decimal(source_alloc["transferred_out_quantity"]) - source_consumed_alloc)
    target_risk = next((r for r in compute_risk(cur, resolve_as_of(None), 0)
                        if int(r["requirement_line_id"]) == target_line_id), None)
    target_transfer_gap = (Decimal(target_risk["covered_by_late_orders"]) + Decimal(target_risk["not_covered"])) if target_risk else ZERO
    if target_transfer_gap <= ZERO:
        raise HTTPException(409, "Stock and on-time orders now cover the receiving project by its need date.")

    donor_line_remaining = _reserved_line(cur, source_line_id)
    donor_consumed = _consumed_line(cur, source_line_id)
    donor_required = max(ZERO, Decimal(source_line["approved_quantity"]) - donor_consumed)
    safe_surplus = max(ZERO, donor_line_remaining - donor_required)
    if body.temporary_borrow:
        if source_line["need_by_date"] <= target["need_by_date"]:
            raise HTTPException(409, "Temporary borrowing is allowed only from a project with a later material need-by date.")
        transferable = min(source_remaining, target_transfer_gap)
    else:
        transferable = min(source_remaining, safe_surplus, target_transfer_gap)
    quantity = Decimal(body.quantity)
    if quantity > transferable:
        raise HTTPException(
            409,
            f"Transfer limit is {_fmt(transferable)} {target['uom_code']}. "
            + ("The donor need-by date must be later, and its allocation will need replenishment." if body.temporary_borrow
               else "This protects the donor project's remaining need and prioritizes the receiving project's at-risk quantity."),
        )

    transfer_notes = body.notes.strip()
    if body.temporary_borrow and not transfer_notes:
        transfer_notes = "Temporary borrow; replenish the donor allocation before " + str(source_line["need_by_date"]) + "."

    cur.execute("""
        UPDATE inventory_allocations
        SET transferred_out_quantity = transferred_out_quantity + %s
        WHERE allocation_id = %s AND allocation_status = 'Active'
    """, (quantity, body.source_allocation_id))
    cur.execute("""
        INSERT INTO inventory_allocations
            (requirement_line_id, warehouse_id, allocated_quantity, transferred_out_quantity,
             allocation_status, allocated_by_user_id, allocated_at, released_at)
        VALUES (%s, %s, %s, 0, 'Active', %s, now(), NULL)
        RETURNING allocation_id
    """, (target_line_id, source_alloc["warehouse_id"], quantity, user_id))
    target_allocation_id = cur.fetchone()["allocation_id"]
    transfer_code = "TRF-" + uuid4().hex[:20].upper()
    cur.execute("""
        INSERT INTO project_allocation_transfers
            (transfer_code, source_allocation_id, target_allocation_id,
             source_requirement_line_id, target_requirement_line_id,
             source_project_id, target_project_id, material_id, warehouse_id,
             quantity, transferred_by_user_id, transferred_at, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s)
        RETURNING transfer_id, transferred_at
    """, (
        transfer_code, body.source_allocation_id, target_allocation_id,
        source_line_id, target_line_id, source_line["project_id"], target["project_id"],
        target["material_id"], source_alloc["warehouse_id"], quantity, user_id, transfer_notes,
    ))
    log = cur.fetchone()
    return {
        "transfer_id": log["transfer_id"],
        "transfer_code": transfer_code,
        "transferred_at": log["transferred_at"],
        "material_code": target["material_code"],
        "material_name": target["material_name"],
        "uom_code": target["uom_code"],
        "quantity": quantity,
        "warehouse_id": source_alloc["warehouse_id"],
        "source_project": {"project_id": source_line["project_id"], "project_code": source_line["project_code"], "name": source_line["project_name"]},
        "target_project": {"project_id": target["project_id"], "project_code": target["project_code"], "name": target["project_name"]},
        "source_allocation_id": body.source_allocation_id,
        "target_allocation_id": target_allocation_id,
        "physical_on_hand_changed": False,
        "temporary_borrow": body.temporary_borrow,
        "message": (f"Temporarily moved {_fmt(quantity)} {target['uom_code']} of {target['material_code']} from {source_line['project_code']} to {target['project_code']}. Replenish {source_line['project_code']} before {source_line['need_by_date']}." if body.temporary_borrow else f"Moved {_fmt(quantity)} {target['uom_code']} of allocated {target['material_code']} from {source_line['project_code']} to {target['project_code']}."),
        "notice": SYNTHETIC_NOTICE,
    }


@router.get("/api/inventory/transfers", tags=["inventory"])
def transfer_history(project_id: int | None = None, limit: int = Query(50, ge=1, le=200),
                     offset: int = Query(0, ge=0), cur=Read):
    cur.execute("""
        SELECT t.transfer_id, t.transfer_code, t.source_project_id, src.project_code AS source_project_code,
               src.name AS source_project_name, t.target_project_id, dst.project_code AS target_project_code,
               dst.name AS target_project_name, t.source_requirement_line_id, t.target_requirement_line_id,
               m.material_code, m.name AS material_name, u.uom_code, w.name AS warehouse,
               t.quantity, t.transferred_at, t.notes, actor.full_name AS transferred_by,
               COUNT(*) OVER() AS _total
        FROM project_allocation_transfers t
        JOIN projects src ON src.project_id = t.source_project_id
        JOIN projects dst ON dst.project_id = t.target_project_id
        JOIN materials m ON m.material_id = t.material_id
        JOIN units_of_measure u ON u.uom_id = m.base_uom_id
        JOIN warehouses w ON w.warehouse_id = t.warehouse_id
        JOIN users actor ON actor.user_id = t.transferred_by_user_id
        WHERE (%(p)s IS NULL OR t.source_project_id = %(p)s OR t.target_project_id = %(p)s)
        ORDER BY t.transferred_at DESC, t.transfer_id DESC
        LIMIT %(l)s OFFSET %(o)s
    """, dict(p=project_id, l=limit, o=offset))
    return paged(cur.fetchall(), limit, offset)