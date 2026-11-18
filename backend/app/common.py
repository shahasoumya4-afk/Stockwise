"""Shared constants and helpers (used by main.py and risk.py)."""
import os
from datetime import date
from typing import Optional

SYNTHETIC_NOTICE = "Synthetic prototype data. Not an approved bill of materials or engineering recommendation."
OPEN_PO_STATUSES = ("Ordered", "Partially Received")


def paged(rows, limit: int, offset: int) -> dict:
    total = rows[0]["_total"] if rows else 0
    items = [{k: v for k, v in r.items() if k != "_total"} for r in rows]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


def resolve_as_of(as_of: Optional[date]) -> date:
    if as_of:
        return as_of
    env = os.getenv("AS_OF_DATE")
    return date.fromisoformat(env) if env else date.today()


# Reserved = allocated minus consumed, for allocations still Active. Allocations reduce
# AVAILABLE stock only; physical on-hand changes only through inventory transactions.
STOCK_CTE = """
WITH consumed AS (
    SELECT allocation_id, -SUM(quantity_delta) AS consumed
    FROM inventory_transactions WHERE transaction_type = 'Consumption' GROUP BY allocation_id
), outstanding AS (
    SELECT a.warehouse_id, r.material_id, SUM(a.allocated_quantity - a.transferred_out_quantity - COALESCE(c.consumed, 0)) AS reserved
    FROM inventory_allocations a
    JOIN project_material_requirements r USING (requirement_line_id)
    LEFT JOIN consumed c USING (allocation_id)
    WHERE a.allocation_status = 'Active'
    GROUP BY a.warehouse_id, r.material_id
), stock AS (
    SELECT i.inventory_id, i.warehouse_id, w.name AS warehouse, i.material_id, m.material_code,
           m.name AS material_name, u.uom_code, i.on_hand_quantity,
           COALESCE(o.reserved, 0) AS reserved_quantity,
           i.on_hand_quantity - COALESCE(o.reserved, 0) AS available_quantity,
           i.safety_stock_quantity, i.reorder_point_quantity, i.updated_at
    FROM inventory i
    JOIN warehouses w ON w.warehouse_id = i.warehouse_id
    JOIN materials m ON m.material_id = i.material_id
    JOIN units_of_measure u ON u.uom_id = m.base_uom_id
    LEFT JOIN outstanding o ON o.warehouse_id = i.warehouse_id AND o.material_id = i.material_id
)
"""
