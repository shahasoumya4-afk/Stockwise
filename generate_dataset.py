#!/usr/bin/env python3
"""
generate_dataset.py - deterministic SYNTHETIC seed-data generator for a fictional
industrial inventory-management portfolio prototype.

*** SYNTHETIC DATA ***  Every record, quantity, price, rule and date produced here is a
fictional assumption. Nothing here is an approved bill of materials, an engineering
recommendation, or derived from any real company's data.

Usage
-----
    python generate_dataset.py --config config.sample.json
    python generate_dataset.py --dump-default-config config.sample.json

Pipeline (each stage has its own seeded RNG stream, so results are reproducible):
  1. parse the material catalogue (source of truth for materials)
  2. master data: departments, roles, users, categories, UoMs, materials, warehouses,
     suppliers, material_suppliers, project_category_material_rules
  3. projects + one approved requirement version + requirement lines per project
     (predicted = synthetic rule baseline, proposed = head-edited, approved = reviewed)
  4. operations: allocations, consumption, purchase orders / receipts, inventory and
     inventory transactions, simulated on a per-(warehouse, material) ledger so stock
     can never go negative and allocations can never exceed available stock
  5. in-generator integrity validation, CSV + manifest output
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
import zlib
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

GENERATOR_VERSION = "1.2.0"
UTC = timezone.utc
SYNTHETIC_LABEL = (
    "SYNTHETIC DATA. Fictional prototype seed data only. All records, quantities, prices, "
    "rules and dates are synthetic assumptions. Not an approved bill of materials, not an "
    "engineering recommendation, and not derived from any real company's data."
)
NO_LOGIN_HASH = "!DISABLED-NO-LOGIN"  # not a valid hash of anything: no usable credentials

# --------------------------------------------------------------------------------------
# Fixed vocabulary
# --------------------------------------------------------------------------------------
CATEGORIES = [  # code, catalogue name, scale_kind, scale_unit, short code
    ("BLAST_FURNACE_UPGRADE", "Blast Furnace Upgrade", "ORDINAL_BAND", "band", "BFU"),
    ("CONVEYOR_SYSTEM_INSTALLATION", "Conveyor System Installation", "LENGTH", "m", "CSI"),
    ("ELECTRICAL_MAINTENANCE_PROJECT", "Electrical Maintenance Project", "EQUIPMENT_COUNT", "items", "EMP"),
    ("COOLING_SYSTEM_UPGRADE", "Cooling System Upgrade", "CAPACITY", "kW", "CSU"),
]
ROLES = [  # placeholders - real application roles may differ
    ("ADMIN", "Administrator", "Placeholder role. No generated user holds it."),
    ("PROJECT_HEAD", "Project Head", "Placeholder role: owns projects and edits estimates."),
    ("INVENTORY_MANAGER", "Inventory Manager", "Placeholder role: reviews estimates, allocates and records stock."),
    ("PROCUREMENT_OFFICER", "Procurement Officer", "Placeholder role: raises purchase orders."),
    ("VIEWER", "Viewer", "Placeholder read-only role."),
]
ROLE_PATTERN = ["PROJECT_HEAD", "PROJECT_HEAD", "INVENTORY_MANAGER", "PROCUREMENT_OFFICER"]
UOM_INFO = {"ea": ("Each", "count"), "kg": ("Kilogram", "mass"), "m": ("Metre", "length"), "L": ("Litre", "volume")}
PROJECT_WORK = {
    "BLAST_FURNACE_UPGRADE": ["Stack Relining", "Hearth Refractory Renewal", "Taphole Zone Repair", "Shell and Lining Refresh"],
    "CONVEYOR_SYSTEM_INSTALLATION": ["Raw-Material Feed Conveyor", "Stockyard Transfer Conveyor", "Coke Handling Conveyor", "Ore Reclaim Conveyor", "Sinter Return Conveyor"],
    "ELECTRICAL_MAINTENANCE_PROJECT": ["Motor Control Centre Refresh", "Cable Route Rehabilitation", "Drive Panel Replacement", "Substation Auxiliary Upgrade"],
    "COOLING_SYSTEM_UPGRADE": ["Cooling Loop Capacity Upgrade", "Cooling Tower Refurbishment", "Heat-Exchanger Loop Replacement", "Process Cooling Pump Station Upgrade"],
}
GREEK = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta", "Iota", "Kappa", "Lambda", "Mu",
         "Nu", "Xi", "Omicron", "Pi", "Rho", "Sigma", "Tau", "Upsilon", "Phi", "Chi", "Psi", "Omega"]

IMPORT_ORDER = [
    "departments", "roles", "users", "project_categories", "material_categories", "units_of_measure",
    "materials", "warehouses", "suppliers", "material_suppliers", "project_category_material_rules",
    "projects", "project_requirement_versions", "project_material_requirements", "inventory",
    "inventory_allocations", "purchase_orders", "purchase_order_lines", "inventory_transactions",
]

_S = {
    "departments": "department_id:BIGINT department_code:VARCHAR(30) name:VARCHAR(100) description:TEXT is_active:BOOLEAN created_at:TIMESTAMPTZ",
    "roles": "role_id:BIGINT role_code:VARCHAR(40) display_name:VARCHAR(100) description:TEXT",
    "users": "user_id:BIGINT employee_id:VARCHAR(30) full_name:VARCHAR(120) email:VARCHAR(255) password_hash:TEXT department_id:BIGINT requested_role_id:BIGINT assigned_role_id:BIGINT account_status:VARCHAR(30) approved_by_user_id:BIGINT approved_at:TIMESTAMPTZ created_at:TIMESTAMPTZ updated_at:TIMESTAMPTZ",
    "project_categories": "project_category_id:BIGINT category_code:VARCHAR(50) name:VARCHAR(100) scale_kind:VARCHAR(30) scale_unit:VARCHAR(20) is_active:BOOLEAN",
    "material_categories": "material_category_id:BIGINT category_code:VARCHAR(50) name:VARCHAR(100) description:TEXT",
    "units_of_measure": "uom_id:BIGINT uom_code:VARCHAR(10) display_name:VARCHAR(50) measurement_type:VARCHAR(30)",
    "materials": "material_id:BIGINT material_code:VARCHAR(20) name:VARCHAR(200) description:TEXT material_category_id:BIGINT base_uom_id:BIGINT is_active:BOOLEAN created_at:TIMESTAMPTZ",
    "warehouses": "warehouse_id:BIGINT warehouse_code:VARCHAR(30) name:VARCHAR(100) location_description:TEXT is_active:BOOLEAN created_at:TIMESTAMPTZ",
    "suppliers": "supplier_id:BIGINT supplier_code:VARCHAR(30) name:VARCHAR(150) contact_name:VARCHAR(120) contact_email:VARCHAR(255) phone:VARCHAR(40) is_active:BOOLEAN created_at:TIMESTAMPTZ",
    "material_suppliers": "material_supplier_id:BIGINT material_id:BIGINT supplier_id:BIGINT supplier_item_code:VARCHAR(50) lead_time_days:INTEGER minimum_order_quantity:NUMERIC(14,3) unit_price:NUMERIC(14,2) currency_code:CHAR(3) is_preferred:BOOLEAN",
    "project_category_material_rules": "rule_id:BIGINT project_category_id:BIGINT material_id:BIGINT scale_band:VARCHAR(10) base_quantity:NUMERIC(14,3) quantity_per_scale_unit:NUMERIC(14,6) rule_version:VARCHAR(30) is_active:BOOLEAN rationale:TEXT",
    "projects": "project_id:BIGINT project_code:VARCHAR(30) name:VARCHAR(200) idea_description:TEXT project_category_id:BIGINT department_id:BIGINT project_head_user_id:BIGINT created_by_user_id:BIGINT scale_level:VARCHAR(20) scale_value:NUMERIC(14,3) equipment_count:INTEGER start_date:DATE end_date:DATE status:VARCHAR(20) created_at:TIMESTAMPTZ updated_at:TIMESTAMPTZ",
    "project_requirement_versions": "requirement_version_id:BIGINT project_id:BIGINT version_number:INTEGER review_status:VARCHAR(30) prediction_method:VARCHAR(60) generated_by_user_id:BIGINT generated_at:TIMESTAMPTZ reviewed_by_user_id:BIGINT reviewed_at:TIMESTAMPTZ review_note:TEXT",
    "project_material_requirements": "requirement_line_id:BIGINT requirement_version_id:BIGINT line_number:INTEGER material_id:BIGINT predicted_quantity:NUMERIC(14,3) proposed_quantity:NUMERIC(14,3) approved_quantity:NUMERIC(14,3) need_by_date:DATE confidence_score:NUMERIC(5,4) rationale:TEXT created_at:TIMESTAMPTZ",
    "inventory": "inventory_id:BIGINT warehouse_id:BIGINT material_id:BIGINT on_hand_quantity:NUMERIC(14,3) safety_stock_quantity:NUMERIC(14,3) reorder_point_quantity:NUMERIC(14,3) updated_at:TIMESTAMPTZ",
    "inventory_allocations": "allocation_id:BIGINT requirement_line_id:BIGINT warehouse_id:BIGINT allocated_quantity:NUMERIC(14,3) allocation_status:VARCHAR(30) allocated_by_user_id:BIGINT allocated_at:TIMESTAMPTZ released_at:TIMESTAMPTZ",
    "purchase_orders": "purchase_order_id:BIGINT po_number:VARCHAR(30) supplier_id:BIGINT warehouse_id:BIGINT order_date:DATE expected_delivery_date:DATE actual_delivery_date:DATE status:VARCHAR(30) created_at:TIMESTAMPTZ",
    "purchase_order_lines": "purchase_order_line_id:BIGINT purchase_order_id:BIGINT line_number:INTEGER material_id:BIGINT ordered_quantity:NUMERIC(14,3) received_quantity:NUMERIC(14,3) unit_price:NUMERIC(14,2) expected_delivery_date:DATE",
    "inventory_transactions": "inventory_transaction_id:BIGINT inventory_id:BIGINT transaction_type:VARCHAR(30) quantity_delta:NUMERIC(14,3) occurred_at:TIMESTAMPTZ project_id:BIGINT requirement_line_id:BIGINT allocation_id:BIGINT purchase_order_line_id:BIGINT recorded_by_user_id:BIGINT reference_code:VARCHAR(40) notes:TEXT created_at:TIMESTAMPTZ",
}
SCHEMA = {t: [tuple(c.split(":", 1)) for c in s.split()] for t, s in _S.items()}

FOREIGN_KEYS = {
    "users": [("department_id", "departments", "department_id"), ("requested_role_id", "roles", "role_id"),
              ("assigned_role_id", "roles", "role_id"), ("approved_by_user_id", "users", "user_id")],
    "materials": [("material_category_id", "material_categories", "material_category_id"), ("base_uom_id", "units_of_measure", "uom_id")],
    "material_suppliers": [("material_id", "materials", "material_id"), ("supplier_id", "suppliers", "supplier_id")],
    "project_category_material_rules": [("project_category_id", "project_categories", "project_category_id"), ("material_id", "materials", "material_id")],
    "projects": [("project_category_id", "project_categories", "project_category_id"), ("department_id", "departments", "department_id"),
                 ("project_head_user_id", "users", "user_id"), ("created_by_user_id", "users", "user_id")],
    "project_requirement_versions": [("project_id", "projects", "project_id"), ("generated_by_user_id", "users", "user_id"),
                                     ("reviewed_by_user_id", "users", "user_id")],
    "project_material_requirements": [("requirement_version_id", "project_requirement_versions", "requirement_version_id"),
                                      ("material_id", "materials", "material_id")],
    "inventory": [("warehouse_id", "warehouses", "warehouse_id"), ("material_id", "materials", "material_id")],
    "inventory_allocations": [("requirement_line_id", "project_material_requirements", "requirement_line_id"),
                              ("warehouse_id", "warehouses", "warehouse_id"), ("allocated_by_user_id", "users", "user_id")],
    "purchase_orders": [("supplier_id", "suppliers", "supplier_id"), ("warehouse_id", "warehouses", "warehouse_id")],
    "purchase_order_lines": [("purchase_order_id", "purchase_orders", "purchase_order_id"), ("material_id", "materials", "material_id")],
    "inventory_transactions": [("inventory_id", "inventory", "inventory_id"), ("project_id", "projects", "project_id"),
                               ("requirement_line_id", "project_material_requirements", "requirement_line_id"),
                               ("allocation_id", "inventory_allocations", "allocation_id"),
                               ("purchase_order_line_id", "purchase_order_lines", "purchase_order_line_id"),
                               ("recorded_by_user_id", "users", "user_id")],
}

# --------------------------------------------------------------------------------------
# Default configuration. EVERYTHING below can be overridden from a JSON config file.
# All quantities, rates, prices and ranges are SYNTHETIC ASSUMPTIONS.
# --------------------------------------------------------------------------------------
def _num(rows):
    return {code: {"base": b, "per_unit": r} for code, b, r in rows}


def _bands(rows):
    return {code: {"small": s, "medium": m, "large": l} for code, s, m, l in rows}


DEFAULT_CONFIG = {
    "seed": 42,
    "output_dir": "data/generated/v1",
    "catalogue_path": "SupplyChain_AI_Project_Overview.md",
    "as_of_date": "2026-10-30",
    "history_years": 3,
    "completed_projects_per_category": 10,
    "active_projects": 5,
    "active_projects_by_category": None,
    "departments": [
        {"code": "MECH", "name": "Mechanical"}, {"code": "ELEC", "name": "Electrical"},
        {"code": "MAINT", "name": "Maintenance"}, {"code": "PROC", "name": "Procurement"},
        {"code": "OPS", "name": "Operations"},
    ],
    "warehouse_count": 3,
    "supplier_count": 8,
    "users_per_department": 4,
    "suppliers_per_material": 2,
    "currency_code": "INR",
    "rule_version": "v1-synthetic",
    "category_departments": {
        "BLAST_FURNACE_UPGRADE": ["OPS", "MECH"],
        "CONVEYOR_SYSTEM_INSTALLATION": ["MECH", "OPS"],
        "ELECTRICAL_MAINTENANCE_PROJECT": ["ELEC", "MAINT"],
        "COOLING_SYSTEM_UPGRADE": ["MECH", "MAINT"],
    },
    "furnace_bands": ["Small", "Medium", "Large"],
    "scale_ranges": {
        "CONVEYOR_SYSTEM_INSTALLATION": {"min": 200, "max": 3000, "step": 50},
        "ELECTRICAL_MAINTENANCE_PROJECT": {"min": 10, "max": 150, "step": 1},
        "COOLING_SYSTEM_UPGRADE": {"min": 500, "max": 6000, "step": 100},
    },
    "duration_days": {
        "BLAST_FURNACE_UPGRADE": [120, 300], "CONVEYOR_SYSTEM_INSTALLATION": [45, 150],
        "ELECTRICAL_MAINTENANCE_PROJECT": [20, 90], "COOLING_SYSTEM_UPGRADE": [60, 180],
    },
    "active_progress_range": [0.2, 0.7],
    "first_project_offset_days": 45,
    "completed_end_buffer_days": 14,
    "need_by_fraction_range": [0.05, 0.85],
    "variation": {
        "project_factor_sigma": 0.08,
        "line_noise_sigma": 0.10,
        "head_edit_probability": 0.7,
        "reviewer_adjust_probability": 0.15,
        "reviewer_adjust_range": [0.03, 0.10],
    },
    "consumption": {
        "completed_fraction_range": [0.92, 1.0],
        "max_chunks": 3,
        "active_pending_line_probability": 0.2,
        "active_pending_allocated_fraction_range": [0.0, 0.5],
    },
    "inventory": {
        "opening_fraction_range": [0.3, 0.8],
        "split_across_warehouses": True,
        "min_split_fraction": 0.25,
        "replenishment_enabled": True,
        "review_interval_days": 7,
        "replenishment_cover_days": 20,
        "safety_stock_days": 14,
        "overbuy_range": [1.0, 1.4],
        "alternate_supplier_probability": 0.2,
        "partial_receipt_probability": 0.35,
        "late_delivery_probability": 0.4,
        "max_late_days": 7,
        "min_delivery_buffer_days": 2,
        "open_po_partial_receipt_probability": 0.4,
        "po_price_jitter": [0.97, 1.03],
    },
    # Optional demo scenario (off by default): thinner stock and more active-project lines waiting on orders,
    # so that WATCH / AT_RISK / SHORT cases appear. Completed-project requirements are NOT affected.
    "stress": {
        "enabled": False,
        "overbuy_range": [1.0, 1.0],
        "replenishment_cover_days": 0,
        "review_interval_days": 21,
        "recent_window_days": 35,
        "recent_extra_delay_days": [14, 45],
        "active_pending_line_probability": 0.9,
        "active_pending_allocated_fraction_range": [0.0, 0.15],
        "no_open_po_probability": 0.25,
        "late_po_probability": 0.35,
        "partial_po_probability": 0.3,
    },
    "quantity_decimals": {"ea": 0, "kg": 0, "m": 1, "L": 0},
    "moq_options_by_uom": {"ea": [1, 5, 10], "kg": [100, 250, 500], "m": [10, 50, 100], "L": [20, 50, 100]},
    "lead_time_days_by_material_category": {
        "Refractory": [21, 60], "Mechanical spare": [30, 90], "Instrumentation": [14, 45],
        "Structural material": [21, 45], "Conveyor spare": [21, 75], "Electrical component": [7, 30],
        "Mechanical/electrical spare": [30, 75], "Cooling equipment": [30, 75], "Piping": [14, 45],
        "Consumable": [7, 21], "Chemical": [7, 21],
    },
    "default_lead_time_range": [14, 45],
    "price_spread": [0.92, 1.10],
    "material_base_prices": {
        "REF-001": 85, "REF-002": 160, "REF-003": 420, "REF-004": 140, "REF-005": 95, "REF-006": 180,
        "REF-007": 14000, "REF-008": 78, "CON-001": 5200, "CON-002": 3800, "CON-003": 3200, "CON-004": 7500,
        "CON-005": 210000, "CON-006": 150000, "CON-007": 480000, "CON-008": 9500, "CON-009": 6200,
        "CON-010": 850, "CON-011": 4800, "ELE-001": 780, "ELE-002": 190, "ELE-003": 18000, "ELE-004": 7500,
        "ELE-005": 3900, "ELE-006": 145000, "ELE-007": 120, "ELE-008": 140, "ELE-009": 45, "ELE-010": 620,
        "ELE-011": 2400, "ELE-012": 260, "SHR-001": 95000, "CLG-001": 185000, "CLG-002": 320000,
        "CLG-003": 1900, "CLG-004": 22000, "CLG-005": 16000, "CLG-006": 9000, "CLG-007": 260000,
        "CLG-008": 190000, "CLG-009": 450, "CLG-010": 2800, "CLG-011": 42000, "CLG-012": 1800,
        "CLG-013": 3600, "CLG-014": 210,
    },
    "default_base_price": 1000,
    # Synthetic quantity rules. Furnace: fixed quantity per band. Others: base + per_unit * scale_value.
    "rules": {
        "BLAST_FURNACE_UPGRADE": _bands([
            ("REF-001", 8000, 20000, 45000), ("REF-002", 4000, 11000, 26000), ("REF-003", 3000, 9000, 20000),
            ("REF-004", 600, 1500, 3200), ("REF-005", 1000, 2500, 6000), ("REF-006", 800, 2200, 5000),
            ("REF-007", 6, 16, 36), ("REF-008", 5000, 15000, 40000), ("CLG-013", 4, 10, 20)]),
        "CONVEYOR_SYSTEM_INSTALLATION": _num([
            ("CON-001", 20, 2.05), ("CON-002", 4, 0.67), ("CON-003", 2, 0.33), ("CON-004", 3, 0.02),
            ("CON-005", 1, 0), ("CON-006", 1, 0), ("CON-007", 1, 0.001), ("CON-008", 4, 0.01),
            ("CON-009", 2, 0.004), ("CON-010", 10, 0.3), ("CON-011", 2, 0.02),
            ("ELE-001", 50, 0.6), ("ELE-002", 80, 1.1), ("ELE-003", 2, 0.004), ("ELE-004", 2, 0.004),
            ("ELE-005", 2, 0.004), ("ELE-006", 1, 0.001), ("ELE-007", 40, 0.1), ("ELE-008", 12, 0.03),
            ("ELE-009", 30, 0.08), ("ELE-010", 20, 0.5), ("ELE-011", 3, 0.01), ("ELE-012", 12, 0.01),
            ("SHR-001", 1, 0.001)]),
        "ELECTRICAL_MAINTENANCE_PROJECT": _num([
            ("ELE-001", 30, 4.0), ("ELE-002", 40, 6.0), ("ELE-003", 2, 0.15), ("ELE-004", 2, 0.2),
            ("ELE-005", 2, 0.2), ("ELE-006", 0, 0.05), ("ELE-007", 30, 4.0), ("ELE-008", 10, 1.5),
            ("ELE-009", 20, 3.0), ("ELE-010", 10, 1.2), ("ELE-011", 2, 0.2), ("ELE-012", 10, 1.0),
            ("SHR-001", 0, 0.08), ("CLG-012", 1, 0.05), ("CLG-013", 1, 0.1)]),
        "COOLING_SYSTEM_UPGRADE": _num([
            ("CLG-001", 2, 0.0006), ("CLG-002", 1, 0.0008), ("CLG-003", 30, 0.06), ("CLG-004", 4, 0.004),
            ("CLG-005", 2, 0.001), ("CLG-006", 1, 0.001), ("CLG-007", 1, 0.0006), ("CLG-008", 1, 0.0008),
            ("CLG-009", 20, 0.05), ("CLG-010", 4, 0.004), ("CLG-011", 1, 0.0003), ("CLG-012", 4, 0.004),
            ("CLG-013", 3, 0.003), ("CLG-014", 50, 0.1),
            ("ELE-001", 40, 0.05), ("ELE-002", 60, 0.08), ("ELE-003", 2, 0.001), ("ELE-004", 2, 0.001),
            ("ELE-005", 2, 0.001), ("ELE-006", 1, 0.0006), ("ELE-007", 30, 0.03), ("ELE-008", 10, 0.01),
            ("ELE-009", 20, 0.02), ("ELE-010", 15, 0.02), ("ELE-011", 2, 0.001), ("ELE-012", 8, 0.005),
            ("SHR-001", 2, 0.0006)]),
    },
}


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------
def deep_merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config(path):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            deep_merge(cfg, json.load(fh))
    return cfg


def stage_rng(seed: int, name: str) -> np.random.Generator:
    return np.random.default_rng([int(seed), zlib.crc32(name.encode("utf-8"))])


def shift_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def dt_at(d: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(d, time(hour, minute), tzinfo=UTC)


def rand_dt(rng, d: date, h0: int = 8, h1: int = 17) -> datetime:
    return datetime.combine(d, time(int(rng.integers(h0, h1 + 1)), int(rng.integers(0, 60))), tzinfo=UTC)


def label(i: int) -> str:
    return GREEK[i % len(GREEK)] + ("" if i < len(GREEK) else str(i // len(GREEK) + 1))


# Quantities are handled internally as integer "milli-units" (value x 1000) to avoid float drift.
def to_step(x: float, step: int) -> int:
    return int(round(x / step)) * step


def floor_step(x: float, step: int) -> int:
    return int(x // step) * step


def ceil_to(x: float, m: int) -> int:
    return int(math.ceil(x / m - 1e-9)) * m


def split_qty(total: int, n: int, step: int, rng) -> list[int]:
    """Split `total` (milli-units) into up to n positive parts that are multiples of `step`."""
    units = total // step
    n = max(1, min(n, units))
    if n == 1:
        return [total]
    cuts = sorted(int(c) for c in rng.choice(np.arange(1, units), size=n - 1, replace=False))
    bounds = [0] + cuts + [units]
    return [(bounds[i + 1] - bounds[i]) * step for i in range(n)]


# --------------------------------------------------------------------------------------
# Catalogue parsing + config validation
# --------------------------------------------------------------------------------------
def parse_catalogue(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Catalogue file not found: {p}. Use --catalogue or set catalogue_path in the config.")
    rows, in_table = [], False
    for raw in p.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s.startswith("|"):
            if in_table:
                break
            continue
        cells = [c.strip().strip("`") for c in s.strip("|").split("|")]
        if not in_table:
            in_table = bool(cells) and cells[0].lower() == "material code"
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if len(cells) != 5:
            raise SystemExit(f"Unexpected catalogue row (expected 5 cells): {raw}")
        rows.append({"code": cells[0], "name": cells[1], "category": cells[2], "uom": cells[3],
                     "candidates": [c.strip() for c in cells[4].split(";") if c.strip()]})
    if not rows:
        raise SystemExit("No material master table found in the catalogue file.")
    codes = [r["code"] for r in rows]
    if len(set(codes)) != len(codes):
        raise SystemExit("Duplicate material codes in catalogue.")
    cat_names = {c[1] for c in CATEGORIES}
    for r in rows:
        if r["uom"] not in UOM_INFO:
            raise SystemExit(f"Unknown unit '{r['uom']}' for {r['code']}")
        bad = [c for c in r["candidates"] if c not in cat_names]
        if bad or not r["candidates"]:
            raise SystemExit(f"{r['code']}: candidate project categories {bad or '(none)'} not in the four allowed categories")
    return rows


def validate_config(cfg, catalogue):
    problems = []
    if cfg["first_project_offset_days"] < 25:
        problems.append("first_project_offset_days must be >= 25 (approval/allocation precede project start)")
    if cfg["users_per_department"] < 3:
        problems.append("users_per_department must be >= 3 (needs at least one inventory manager)")
    if cfg["suppliers_per_material"] > cfg["supplier_count"] or cfg["suppliers_per_material"] < 1:
        problems.append("suppliers_per_material must be between 1 and supplier_count")
    if cfg["warehouse_count"] < 1:
        problems.append("warehouse_count must be >= 1")
    if cfg["active_projects"] < len(CATEGORIES) and not cfg.get("active_projects_by_category"):
        problems.append("active_projects must be >= 4 so every category has at least one active project")
    if cfg["history_years"] < 1:
        problems.append("history_years must be >= 1")
    for k, (lo, hi) in cfg["lead_time_days_by_material_category"].items():
        if lo < 7 or hi < lo:
            problems.append(f"lead time range for {k} must satisfy 7 <= min <= max")
    if cfg["default_lead_time_range"][0] < 7:
        problems.append("default_lead_time_range min must be >= 7")
    dept_codes = {d["code"] for d in cfg["departments"]}
    for code, name, kind, unit, abbr in CATEGORIES:
        for dc in cfg["category_departments"].get(code, []):
            if dc not in dept_codes:
                problems.append(f"category_departments[{code}] references unknown department {dc}")
        if not cfg["category_departments"].get(code):
            problems.append(f"category_departments[{code}] is empty")
        cand = [m["code"] for m in catalogue if name in m["candidates"]]
        rules = cfg["rules"].get(code, {})
        if set(rules) != set(cand):
            problems.append(f"rules[{code}] must cover exactly the catalogue candidates; "
                            f"missing={sorted(set(cand) - set(rules))} extra={sorted(set(rules) - set(cand))}")
        for mc, spec in rules.items():
            if kind == "ORDINAL_BAND":
                need = {b.lower() for b in cfg["furnace_bands"]}
                if set(spec) != need:
                    problems.append(f"rules[{code}][{mc}] must define bands {sorted(need)}")
            elif set(spec) != {"base", "per_unit"}:
                problems.append(f"rules[{code}][{mc}] must define 'base' and 'per_unit'")
        if kind != "ORDINAL_BAND":
            sr = cfg["scale_ranges"].get(code)
            if not sr or sr["min"] > sr["max"] or sr["step"] <= 0:
                problems.append(f"scale_ranges[{code}] invalid")
        lo, hi = cfg["duration_days"][code]
        if lo < 1 or hi < lo:
            problems.append(f"duration_days[{code}] invalid")
    if problems:
        raise SystemExit("Configuration problems:\n  - " + "\n  - ".join(problems))


# --------------------------------------------------------------------------------------
# Stage 1: master data
# --------------------------------------------------------------------------------------
def build_masters(cfg, catalogue, ctx):
    seed, as_of = cfg["seed"], ctx["as_of"]
    master_ts = dt_at(ctx["hist_start"] - timedelta(days=90), 8)
    R = {}

    R["departments"] = pd.DataFrame([dict(
        department_id=i + 1, department_code=d["code"], name=d["name"],
        description=f"Synthetic department record: {d['name']}. Fictional.", is_active=True, created_at=master_ts)
        for i, d in enumerate(cfg["departments"])])
    R["roles"] = pd.DataFrame([dict(role_id=i + 1, role_code=c, display_name=n, description=d)
                               for i, (c, n, d) in enumerate(ROLES)])
    role_id = {c: i + 1 for i, (c, _, _) in enumerate(ROLES)}

    users = []
    for d in R["departments"].itertuples():
        for k in range(cfg["users_per_department"]):
            uid = len(users) + 1
            role = ROLE_PATTERN[k % len(ROLE_PATTERN)]
            users.append(dict(
                user_id=uid, employee_id=f"SYN-EMP-{uid:04d}", full_name=f"Demo Employee {uid:03d}",
                email=f"demo.employee.{uid:04d}@example.invalid", password_hash=NO_LOGIN_HASH,
                department_id=d.department_id, requested_role_id=role_id[role], assigned_role_id=role_id[role],
                account_status="Disabled", approved_by_user_id=None, approved_at=None,
                created_at=master_ts, updated_at=master_ts, _role=role))
    R["users"] = pd.DataFrame(users)

    R["project_categories"] = pd.DataFrame([dict(
        project_category_id=i + 1, category_code=c, name=n, scale_kind=k, scale_unit=u, is_active=True)
        for i, (c, n, k, u, _) in enumerate(CATEGORIES)])

    mcat_names = list(dict.fromkeys(m["category"] for m in catalogue))
    R["material_categories"] = pd.DataFrame([dict(
        material_category_id=i + 1, category_code=re.sub(r"[^A-Z0-9]+", "_", n.upper()).strip("_"), name=n,
        description=f"Synthetic grouping '{n}' taken from the fictional starter catalogue.")
        for i, n in enumerate(mcat_names)])
    mcat_id = {n: i + 1 for i, n in enumerate(mcat_names)}

    uoms = list(dict.fromkeys(m["uom"] for m in catalogue))
    R["units_of_measure"] = pd.DataFrame([dict(uom_id=i + 1, uom_code=u, display_name=UOM_INFO[u][0],
                                               measurement_type=UOM_INFO[u][1]) for i, u in enumerate(uoms)])
    uom_id = {u: i + 1 for i, u in enumerate(uoms)}

    R["materials"] = pd.DataFrame([dict(
        material_id=i + 1, material_code=m["code"], name=m["name"],
        description="Synthetic catalogue item (fictional starter material; seed data only).",
        material_category_id=mcat_id[m["category"]], base_uom_id=uom_id[m["uom"]], is_active=True,
        created_at=master_ts) for i, m in enumerate(catalogue)])

    R["warehouses"] = pd.DataFrame([dict(
        warehouse_id=i + 1, warehouse_code=f"SYN-WH-{i + 1:02d}", name=f"Synthetic Warehouse {label(i)}",
        location_description=f"Fictional storage zone {i + 1}. Not a real site.", is_active=True,
        created_at=master_ts) for i in range(cfg["warehouse_count"])])

    R["suppliers"] = pd.DataFrame([dict(
        supplier_id=i + 1, supplier_code=f"SYN-SUP-{i + 1:03d}", name=f"Synthetic Supplier {label(i)}",
        contact_name=f"Demo Contact {i + 1:02d}", contact_email=f"contact.sup{i + 1:03d}@example.invalid",
        phone=f"+00-000-{i + 1:07d}", is_active=True, created_at=master_ts)
        for i in range(cfg["supplier_count"])])

    # material_suppliers
    rng = stage_rng(seed, "material_suppliers")
    n_sup, k = cfg["supplier_count"], cfg["suppliers_per_material"]
    ms_rows = []
    for idx, m in enumerate(catalogue):
        primary = idx % n_sup  # round-robin guarantees every supplier supplies something
        others = [s for s in range(n_sup) if s != primary]
        chosen = [primary] + ([int(x) for x in rng.choice(others, size=k - 1, replace=False)] if k > 1 else [])
        base_price = float(cfg["material_base_prices"].get(m["code"], cfg["default_base_price"]))
        lo, hi = cfg["lead_time_days_by_material_category"].get(m["category"], cfg["default_lead_time_range"])
        for j, s in enumerate(chosen):
            price = round(base_price * float(rng.uniform(*cfg["price_spread"])), 2)
            moq_units = 1 if price >= 10000 else int(rng.choice(cfg["moq_options_by_uom"][m["uom"]]))
            ms_rows.append(dict(
                material_supplier_id=len(ms_rows) + 1, material_id=idx + 1, supplier_id=s + 1,
                supplier_item_code=f"SUP{s + 1:03d}-{m['code']}", lead_time_days=int(rng.integers(lo, hi + 1)),
                minimum_order_quantity=float(moq_units), unit_price=price, currency_code=cfg["currency_code"],
                is_preferred=(j == 0)))
    R["material_suppliers"] = pd.DataFrame(ms_rows)

    # rules
    rules, mid_by_code = [], {m["code"]: i + 1 for i, m in enumerate(catalogue)}
    for cid, (code, name, kind, unit, _) in enumerate(CATEGORIES, start=1):
        for m in catalogue:  # catalogue order
            if m["code"] not in cfg["rules"][code]:
                continue
            spec = cfg["rules"][code][m["code"]]
            note = (f"SYNTHETIC ASSUMPTION ({cfg['rule_version']}): fictional baseline for {name}; "
                    "not an engineering recommendation or approved bill of materials.")
            if kind == "ORDINAL_BAND":
                for b in cfg["furnace_bands"]:
                    rules.append(dict(rule_id=len(rules) + 1, project_category_id=cid, material_id=mid_by_code[m["code"]],
                                      scale_band=b.lower(), base_quantity=float(spec[b.lower()]),
                                      quantity_per_scale_unit=None, rule_version=cfg["rule_version"], is_active=True,
                                      rationale=note + f" Fixed quantity for the {b} band."))
            else:
                rules.append(dict(rule_id=len(rules) + 1, project_category_id=cid, material_id=mid_by_code[m["code"]],
                                  scale_band="all", base_quantity=float(spec["base"]),
                                  quantity_per_scale_unit=float(spec["per_unit"]), rule_version=cfg["rule_version"],
                                  is_active=True, rationale=note + f" Quantity = base + rate x scale ({unit})."))
    R["project_category_material_rules"] = pd.DataFrame(rules)
    ctx["master_ts"] = master_ts
    return R


# --------------------------------------------------------------------------------------
# Stage 2: projects, requirement versions, requirement lines
# --------------------------------------------------------------------------------------
def build_projects(cfg, catalogue, R, ctx):
    seed, as_of, hist_start = cfg["seed"], ctx["as_of"], ctx["hist_start"]
    rng = stage_rng(seed, "projects")
    cat_id = {c[0]: i + 1 for i, c in enumerate(CATEGORIES)}
    dept_id = dict(zip(R["departments"].department_code, R["departments"].department_id))
    users = R["users"]
    heads_by_dept = {d: users[(users.department_id == d) & (users._role == "PROJECT_HEAD")].user_id.tolist()
                     for d in R["departments"].department_id}
    inv_mgrs = users[users._role == "INVENTORY_MANAGER"].user_id.tolist()
    ctx["inv_mgrs"] = inv_mgrs
    mat = R["materials"].set_index("material_id")
    uom_code = dict(zip(R["units_of_measure"].uom_id, R["units_of_measure"].uom_code))
    mat_uom = {mid: uom_code[r.base_uom_id] for mid, r in mat.iterrows()}
    ctx["mat_step"] = {mid: 10 ** (3 - int(cfg["quantity_decimals"][u])) for mid, u in mat_uom.items()}
    ctx["mat_uom"] = mat_uom

    # active counts
    ov = cfg.get("active_projects_by_category")
    codes = [c[0] for c in CATEGORIES]
    if ov:
        active = {c: int(ov.get(c, 0)) for c in codes}
        if min(active.values()) < 1:
            raise SystemExit("active_projects_by_category must give every category at least 1 project")
    else:
        n = int(cfg["active_projects"])
        base, rem = divmod(n, len(codes))
        active = {c: base for c in codes}
        for c in rng.choice(codes, size=rem, replace=False):
            active[str(c)] += 1

    first_start = hist_start + timedelta(days=int(cfg["first_project_offset_days"]))
    buf = int(cfg["completed_end_buffer_days"])
    specs = []
    for ci, (code, name, kind, unit, abbr) in enumerate(CATEGORIES):
        for status, n in (("Completed", int(cfg["completed_projects_per_category"])), ("Active", active[code])):
            if n <= 0:
                continue
            if kind == "ORDINAL_BAND":
                bands = (list(cfg["furnace_bands"]) * math.ceil(n / len(cfg["furnace_bands"])))[:n]
                rng.shuffle(bands)
                scales = [(b, None) for b in bands]
            else:
                sr = cfg["scale_ranges"][code]
                steps = int((sr["max"] - sr["min"]) // sr["step"])
                scales = [(None, sr["min"] + sr["step"] * int(rng.integers(0, steps + 1))) for _ in range(n)]
            for i in range(n):
                lo, hi = cfg["duration_days"][code]
                dur = int(rng.integers(lo, hi + 1))
                if status == "Completed":
                    latest = as_of - timedelta(days=buf + dur)
                    span = (latest - first_start).days
                    if span < 0:
                        raise SystemExit("history window too short for the configured project durations")
                    start = first_start + timedelta(days=int(rng.integers(0, span + 1)))
                else:
                    prog = float(rng.uniform(*cfg["active_progress_range"]))
                    start = as_of - timedelta(days=int(round(prog * dur)))
                    start = max(start, first_start)
                end = start + timedelta(days=dur)
                if status == "Active" and not (start <= as_of < end):
                    end = as_of + timedelta(days=max(7, dur // 4))
                dep = dept_id[str(rng.choice(cfg["category_departments"][code]))]
                head = int(rng.choice(heads_by_dept[dep]))
                specs.append(dict(ci=ci, code=code, name_=name, kind=kind, unit=unit, abbr=abbr, status=status,
                                  level=scales[i][0], value=scales[i][1], start=start, end=end, dur=(end - start).days,
                                  dept=dep, head=head, work=PROJECT_WORK[code][int(rng.integers(0, len(PROJECT_WORK[code])))]))
    specs.sort(key=lambda s: (s["start"], s["ci"]))

    rule_rows = R["project_category_material_rules"]
    rules_by = {}
    for r in rule_rows.itertuples():
        rules_by.setdefault((r.project_category_id, r.scale_band), []).append(r)

    seq, projects, versions, lines = {}, [], [], []
    nb_lo, nb_hi = cfg["need_by_fraction_range"]
    var = cfg["variation"]
    rng2 = stage_rng(seed, "requirements")
    for pid, s in enumerate(specs, start=1):
        seq[s["abbr"]] = seq.get(s["abbr"], 0) + 1
        if s["kind"] == "ORDINAL_BAND":
            sc = f"{s['level']} furnace scale band"
        elif s["kind"] == "LENGTH":
            sc = f"{int(s['value']):,} m conveyor length"
        elif s["kind"] == "EQUIPMENT_COUNT":
            sc = f"{int(s['value'])} equipment items"
        else:
            sc = f"{int(s['value']):,} kW cooling capacity"
        gen_at = dt_at(s["start"] - timedelta(days=21), 9)
        reviewed_at = gen_at + timedelta(days=3)
        created_at = gen_at - timedelta(days=2)
        updated_at = reviewed_at if s["status"] == "Active" else dt_at(s["end"] + timedelta(days=1), 12)
        projects.append(dict(
            project_id=pid, project_code=f"SYN-{s['abbr']}-{seq[s['abbr']]:04d}",
            name=f"{s['work']} - Unit {label(seq[s['abbr']] - 1)}",
            idea_description=f"Fictional demo scenario: {s['work'].lower()} ({sc}). Synthetic record; not a real project.",
            project_category_id=s["ci"] + 1, department_id=s["dept"], project_head_user_id=s["head"],
            created_by_user_id=s["head"], scale_level=s["level"], scale_value=s["value"],
            equipment_count=int(s["value"]) if s["kind"] == "EQUIPMENT_COUNT" else None,
            start_date=s["start"], end_date=s["end"], status=s["status"], created_at=created_at, updated_at=updated_at,
            _status=s["status"]))
        versions.append(dict(
            requirement_version_id=pid, project_id=pid, version_number=1, review_status="Approved",
            prediction_method="SYNTHETIC_RULE_BASELINE", generated_by_user_id=None, generated_at=gen_at,
            reviewed_by_user_id=int(rng2.choice(ctx["inv_mgrs"])), reviewed_at=reviewed_at,
            review_note="Synthetic seed record: estimate approved automatically by the generator."))
        band = s["level"].lower() if s["kind"] == "ORDINAL_BAND" else "all"
        pf = float(np.exp(rng2.normal(0, var["project_factor_sigma"])))
        for ln, rule in enumerate(rules_by[(s["ci"] + 1, band)], start=1):
            step = ctx["mat_step"][rule.material_id]
            raw = rule.base_quantity if band != "all" else rule.base_quantity + rule.quantity_per_scale_unit * float(s["value"])
            pred = max(step, to_step(raw * 1000, step))
            noise = float(np.exp(rng2.normal(0, var["line_noise_sigma"])))
            edited = rng2.random() < var["head_edit_probability"]
            prop = max(step, to_step(pred * pf * noise, step)) if edited else pred
            adjusted = rng2.random() < var["reviewer_adjust_probability"]
            if adjusted:
                sign = 1 if rng2.random() < 0.5 else -1
                appr = max(step, to_step(prop * (1 + sign * float(rng2.uniform(*var["reviewer_adjust_range"]))), step))
            else:
                appr = prop
            frac = float(rng2.uniform(nb_lo, nb_hi))
            need = s["start"] + timedelta(days=int(s["dur"] * frac))
            why = f"Synthetic seed estimate from rule {rule.rule_id} ({rule.rule_version}); not an approved bill of materials."
            if edited and prop != pred:
                why += " Project-head edit applied (synthetic)."
            if adjusted and appr != prop:
                why += " Reviewer adjustment applied (synthetic)."
            lines.append(dict(
                requirement_line_id=len(lines) + 1, requirement_version_id=pid, line_number=ln,
                material_id=int(rule.material_id), predicted_quantity=pred / 1000, proposed_quantity=prop / 1000,
                approved_quantity=appr / 1000, need_by_date=need, confidence_score=None, rationale=why,
                created_at=gen_at, _approved=appr, _project_id=pid, _step=step))
    R["projects"] = pd.DataFrame(projects)
    R["project_requirement_versions"] = pd.DataFrame(versions)
    ctx["lines"] = lines
    R["project_material_requirements"] = pd.DataFrame(lines)
    ctx["proj"] = {p["project_id"]: dict(p, alloc_ts=dt_at(p["start_date"] - timedelta(days=21) + timedelta(days=4), 10))
                   for p in projects}


# --------------------------------------------------------------------------------------
# Stage 3: allocations, consumption, purchase orders, inventory, transactions
# --------------------------------------------------------------------------------------
class Ledger:
    """Per (warehouse, material) stock ledger used to plan receipts and allocations."""
    __slots__ = ("opening", "receipts", "allocs")

    def __init__(self, opening: int):
        self.opening, self.receipts, self.allocs = opening, [], []

    def available(self, ts) -> int:
        a = self.opening
        for t, q, _od in self.receipts:
            if t <= ts:
                a += q
        for al in self.allocs:
            if al["alloc_ts"] <= ts:
                a -= al["qty"]
                if al["release_ts"] is not None and al["release_ts"] <= ts:
                    a += al["release_qty"]
        return a


def build_operations(cfg, catalogue, R, ctx):
    seed, as_of, hist_start = cfg["seed"], ctx["as_of"], ctx["hist_start"]
    rng = stage_rng(seed, "operations")
    inv_cfg, con_cfg = cfg["inventory"], cfg["consumption"]
    stress = cfg["stress"]
    stress_on = bool(stress["enabled"])
    if stress_on:
        inv_cfg = dict(inv_cfg, overbuy_range=stress["overbuy_range"], replenishment_cover_days=stress["replenishment_cover_days"],
                       review_interval_days=stress["review_interval_days"])
        con_cfg = dict(con_cfg, active_pending_line_probability=stress["active_pending_line_probability"],
                       active_pending_allocated_fraction_range=stress["active_pending_allocated_fraction_range"])
    wh_ids = R["warehouses"].warehouse_id.tolist()
    n_wh = len(wh_ids)
    mat_ids = R["materials"].material_id.tolist()
    step_of, proj = ctx["mat_step"], ctx["proj"]
    inv_mgrs = ctx["inv_mgrs"]

    ms_by_mat = {}
    for r in R["material_suppliers"].itertuples():
        ms_by_mat.setdefault(r.material_id, []).append(dict(
            ms_id=r.material_supplier_id, supplier_id=r.supplier_id, lead=int(r.lead_time_days),
            moq=int(round(r.minimum_order_quantity * 1000)), price=float(r.unit_price), preferred=bool(r.is_preferred)))
    for v in ms_by_mat.values():
        v.sort(key=lambda d: (not d["preferred"], d["ms_id"]))

    # ledgers with synthetic opening balances
    sums, cnts = {}, {}
    for ln in ctx["lines"]:
        sums[ln["material_id"]] = sums.get(ln["material_id"], 0) + ln["_approved"]
        cnts[ln["material_id"]] = cnts.get(ln["material_id"], 0) + 1
    ledgers = {}
    for wh in wh_ids:
        for mid in mat_ids:
            st = step_of[mid]
            mean_q = sums.get(mid, 0) / cnts[mid] if cnts.get(mid) else 0
            opening = max(st, to_step(mean_q * float(rng.uniform(*inv_cfg["opening_fraction_range"])), st))
            ledgers[(wh, mid)] = Ledger(opening)

    po_lines, pieces = [], []

    def pick_supplier(mid):
        lst = ms_by_mat[mid]
        if len(lst) > 1 and rng.random() < inv_cfg["alternate_supplier_probability"]:
            return lst[1 + int(rng.integers(0, len(lst) - 1))]
        return lst[0]

    def add_receipts_and_line(mid, wh, ms, order_date, expected, order_qty, receipts):
        lo, hi = inv_cfg["po_price_jitter"]
        po_lines.append(dict(order_date=order_date, supplier_id=ms["supplier_id"], wh=wh, material_id=mid,
                             ordered=order_qty, receipts=receipts, unit_price=round(ms["price"] * float(rng.uniform(lo, hi)), 2),
                             expected=expected))

    def procure(ledger, wh, mid, qty, alloc_ts):
        """Back-dated purchase that delivers `qty` (plus overbuy) before alloc_ts, or bump opening stock."""
        st, ms = step_of[mid], pick_supplier(mid)
        slip = int(rng.integers(1, inv_cfg["max_late_days"] + 1)) if rng.random() < inv_cfg["late_delivery_probability"] else 0
        buffer_d = int(inv_cfg["min_delivery_buffer_days"]) + int(rng.integers(0, 6))
        expected = alloc_ts.date() - timedelta(days=buffer_d + slip)
        raw_order = expected - timedelta(days=ms["lead"])
        order_date = raw_order - timedelta(days=raw_order.weekday())  # place orders on Mondays
        if order_date < hist_start:
            ledger.opening += qty  # early demand is covered by the (synthetic) opening balance instead
            return
        expected = order_date + timedelta(days=ms["lead"])
        final = expected + timedelta(days=slip)
        order_qty = ceil_to(qty * float(rng.uniform(*inv_cfg["overbuy_range"])), ms["moq"])
        n_rec = int(rng.integers(2, 4)) if rng.random() < inv_cfg["partial_receipt_probability"] else 1
        parts = split_qty(order_qty, n_rec, st, rng)
        dates = [final]
        for _ in range(len(parts) - 1):
            dates.insert(0, dates[0] - timedelta(days=int(rng.integers(2, 15))))
        dates = sorted(max(d, order_date + timedelta(days=1)) for d in dates)
        receipts = [(rand_dt(rng, d, 8, 12), q) for d, q in zip(dates, parts)]
        ledger.receipts.extend((t_, q_, order_date) for t_, q_ in receipts)
        add_receipts_and_line(mid, wh, ms, order_date, expected, order_qty, receipts)

    def make_piece(rq, wh, qty):
        st = step_of[rq["material_id"]]
        cons_total = min(qty, to_step(qty * rq["cons_frac"], st))
        chunks = []
        if cons_total > 0:
            n = min(int(rng.integers(1, con_cfg["max_chunks"] + 1)), cons_total // st)
            parts = split_qty(cons_total, n, st, rng)
            c0 = max(rq["c_start"], rq["alloc_ts"].date() + timedelta(days=1))
            c1 = max(rq["c_end"], c0)
            offs = sorted(int(rng.integers(0, (c1 - c0).days + 1)) for _ in parts)
            chunks = [(rand_dt(rng, c0 + timedelta(days=o), 8, 17), q) for o, q in zip(offs, parts)]
        release_ts, release_qty = None, 0
        if rq["status"] == "Completed":
            if cons_total < qty:
                release_qty, release_ts = qty - cons_total, dt_at(rq["end_date"] + timedelta(days=1), 10)
            status = "Released" if release_qty else "Consumed"
        else:
            status = "Consumed" if cons_total == qty else "Active"
        piece = dict(line_id=rq["line_id"], project_id=rq["project_id"], material_id=rq["material_id"], wh=wh, qty=qty,
                     alloc_ts=rq["alloc_ts"], status=status, release_ts=release_ts, release_qty=release_qty,
                     cons=chunks, user=int(rng.choice(inv_mgrs)))
        ledgers[(wh, rq["material_id"])].allocs.append(piece)
        pieces.append(piece)

    # build allocation requests
    reqs = []
    for ln in ctx["lines"]:
        p = proj[ln["_project_id"]]
        Q, need = ln["_approved"], ln["need_by_date"]
        pending, cf = False, 0.0
        if p["status"] == "Completed":
            target, cf, c_end = Q, float(rng.uniform(*con_cfg["completed_fraction_range"])), p["end_date"]
        else:
            c_end = as_of
            if need > as_of and rng.random() < con_cfg["active_pending_line_probability"]:
                pending = True
                target = floor_step(Q * float(rng.uniform(*con_cfg["active_pending_allocated_fraction_range"])), ln["_step"])
            else:
                target = Q
                if need <= as_of:
                    span = max(1, (p["end_date"] - need).days)
                    cf = min(1.0, max(0.1, (as_of - need).days / span * float(rng.uniform(0.8, 1.4))))
        reqs.append(dict(line_id=ln["requirement_line_id"], project_id=p["project_id"], material_id=ln["material_id"],
                         line_number=ln["line_number"], total=Q, target=target, pending=pending, cons_frac=cf,
                         c_start=need, c_end=c_end, status=p["status"], end_date=p["end_date"], alloc_ts=p["alloc_ts"]))
    reqs.sort(key=lambda r: (r["alloc_ts"], r["project_id"], r["line_number"]))

    for rq in reqs:
        if rq["target"] <= 0:
            continue
        mid = rq["material_id"]
        pref = wh_ids[(rq["project_id"] + mid) % n_wh]
        i0 = wh_ids.index(pref)
        order = [wh_ids[(i0 + k) % n_wh] for k in range(n_wh)] if inv_cfg["split_across_warehouses"] else [pref]
        remaining = rq["target"]
        # prefer a single source: first warehouse (preferred first) that can cover the whole line
        full = next((w for w in order if ledgers[(w, mid)].available(rq["alloc_ts"]) >= remaining), None)
        if full is not None:
            make_piece(rq, full, remaining)
            continue
        pooled = sum(ledgers[(w, mid)].available(rq["alloc_ts"]) for w in order)
        # split across warehouses only when that avoids a purchase; otherwise buy the whole line for the preferred one
        for wh in (order if pooled >= remaining else []):
            if remaining <= 0:
                break
            take = min(ledgers[(wh, mid)].available(rq["alloc_ts"]), remaining)
            # only draw from a non-preferred warehouse when it covers a meaningful share of the line
            if wh != pref and take < remaining * inv_cfg["min_split_fraction"]:
                continue
            if take > 0:
                make_piece(rq, wh, take)
                remaining -= take
        if remaining > 0:
            procure(ledgers[(pref, mid)], pref, mid, remaining, rq["alloc_ts"])
            assert ledgers[(pref, mid)].available(rq["alloc_ts"]) >= remaining, "procurement planning failed"
            make_piece(rq, pref, remaining)

    # open purchase orders covering the unallocated part of pending lines on active projects
    for rq in reqs:
        if not rq["pending"]:
            continue
        mid, st = rq["material_id"], step_of[rq["material_id"]]
        wh = wh_ids[(rq["project_id"] + mid) % n_wh]
        ms = pick_supplier(mid)
        qty = rq["total"] - rq["target"]
        if stress_on:
            roll = rng.random()
            if roll < stress["no_open_po_probability"]:
                continue  # nothing on order for this gap yet
            need_by, lead = rq["c_start"], ms["lead"]
            lo, cap = as_of + timedelta(days=3), as_of + timedelta(days=lead - 1)  # a new order must already be placed
            late = roll < stress["no_open_po_probability"] + stress["late_po_probability"]
            expected = None
            for want_late in ([True, False] if late else [False, True]):
                a, b = (need_by + timedelta(days=1), cap) if want_late else (lo, min(need_by - timedelta(days=2), cap))
                if a <= b:
                    expected = a + timedelta(days=int(rng.integers(0, (b - a).days + 1)))
                    break
            if expected is None:
                continue
            if rng.random() < stress["partial_po_probability"]:
                qty = max(st, floor_step(qty * float(rng.uniform(0.3, 0.7)), st))
            order_date = expected - timedelta(days=lead)
            order_qty = ceil_to(qty * float(rng.uniform(1.0, 1.1)), ms["moq"])
            offset = max(1, (as_of - order_date).days)
        else:
            order_qty = ceil_to(qty * float(rng.uniform(1.0, 1.1)), ms["moq"])
            offset = 1 + int(rng.integers(0, max(1, ms["lead"] - 3)))
            order_date = as_of - timedelta(days=offset)
            expected = order_date + timedelta(days=ms["lead"])
        receipts = []
        if rng.random() < inv_cfg["open_po_partial_receipt_probability"]:
            q1 = max(st, floor_step(order_qty * float(rng.uniform(0.2, 0.6)), st))
            d1 = order_date + timedelta(days=int(rng.integers(1, offset + 1)))
            receipts = [(rand_dt(rng, d1, 8, 12), q1)]
            ledgers[(wh, mid)].receipts.extend((t_, q_, order_date) for t_, q_ in receipts)
        add_receipts_and_line(mid, wh, ms, order_date, expected, order_qty, receipts)

    # ---- reorder parameters (synthetic policy) from per-warehouse consumption history ----
    hist_days = max(1, (as_of - hist_start).days)
    cons_wm = {}
    for p in pieces:
        k = (p["wh"], p["material_id"])
        cons_wm[k] = cons_wm.get(k, 0) + sum(q for _, q in p["cons"])
    params = {}
    for (wh, mid) in ledgers:
        st = step_of[mid]
        daily = cons_wm.get((wh, mid), 0) / hist_days
        safety = ceil_to(daily * inv_cfg["safety_stock_days"], st)
        rop = safety + ceil_to(daily * ms_by_mat[mid][0]["lead"], st)
        params[(wh, mid)] = (safety, rop, rop + ceil_to(daily * inv_cfg["replenishment_cover_days"], st))

    # ---- routine replenishment: weekly review, order up to a target when position <= reorder point ----
    # Receipts only ever ADD stock, so this cannot break any allocation / non-negative-stock guarantee.
    if inv_cfg["replenishment_enabled"]:
        first = hist_start + timedelta(days=7)
        first += timedelta(days=(7 - first.weekday()) % 7)  # a Monday
        as_of_end = dt_at(as_of, 23, 59)
        for (wh, mid), led in ledgers.items():
            safety, rop, up_to = params[(wh, mid)]
            if up_to <= 0:
                continue
            st, day = step_of[mid], first
            while day <= as_of:
                ts = dt_at(day, 12)
                position = led.available(ts) + sum(q for t_, q, od in led.receipts if t_ > ts and od <= day)
                if position <= rop:
                    ms = pick_supplier(mid)
                    need = up_to - position
                    qty = ceil_to(need if need > 0 else st, ms["moq"])
                    slip = int(rng.integers(1, inv_cfg["max_late_days"] + 1)) if rng.random() < inv_cfg["late_delivery_probability"] else 0
                    expected = day + timedelta(days=ms["lead"])
                    if stress_on and (as_of - day).days <= stress["recent_window_days"]:
                        lo_d, hi_d = stress["recent_extra_delay_days"]
                        expected += timedelta(days=int(rng.integers(lo_d, hi_d + 1)))  # supplier delay on recent orders
                    final = expected + timedelta(days=slip)
                    n_rec = int(rng.integers(2, 4)) if rng.random() < inv_cfg["partial_receipt_probability"] else 1
                    parts = split_qty(qty, n_rec, st, rng)
                    dates = [final]
                    for _ in range(len(parts) - 1):
                        dates.insert(0, dates[0] - timedelta(days=int(rng.integers(2, 15))))
                    dates = sorted(max(d, day + timedelta(days=1)) for d in dates)
                    planned = [(rand_dt(rng, d, 8, 12), q) for d, q in zip(dates, parts)]
                    led.receipts.extend((t_, q, day) for t_, q in planned)  # still-open deliveries count as on order
                    add_receipts_and_line(mid, wh, ms, day, expected, qty, [(t_, q) for t_, q in planned if t_ <= as_of_end])
                day += timedelta(days=int(inv_cfg["review_interval_days"]))

    # ---------------- assemble tables ----------------
    # allocations
    pieces.sort(key=lambda p: (p["alloc_ts"], p["line_id"], p["wh"]))
    for i, p in enumerate(pieces, start=1):
        p["id"] = i
    R["inventory_allocations"] = pd.DataFrame([dict(
        allocation_id=p["id"], requirement_line_id=p["line_id"], warehouse_id=p["wh"], allocated_quantity=p["qty"] / 1000,
        allocation_status=p["status"], allocated_by_user_id=p["user"], allocated_at=p["alloc_ts"],
        released_at=p["release_ts"]) for p in pieces])

    # purchase orders
    po_lines.sort(key=lambda l: (l["order_date"], l["supplier_id"], l["wh"], l["material_id"]))
    headers = {}
    for l in po_lines:
        headers.setdefault((l["order_date"], l["supplier_id"], l["wh"]), []).append(l)
    po_rows, pol_rows, lid = [], [], 0
    for hid, (key, ls) in enumerate(headers.items(), start=1):
        order_date, sup, wh = key
        statuses_full = [sum(q for _, q in l["receipts"]) == l["ordered"] for l in ls]
        any_recv = any(l["receipts"] for l in ls)
        status = "Received" if all(statuses_full) else ("Partially Received" if any_recv else "Ordered")
        last = max((t.date() for l in ls for t, _ in l["receipts"]), default=None)
        po_rows.append(dict(
            purchase_order_id=hid, po_number=f"SYN-PO-{hid:06d}", supplier_id=sup, warehouse_id=wh, order_date=order_date,
            expected_delivery_date=max(l["expected"] for l in ls),
            actual_delivery_date=last if status == "Received" else None, status=status,
            created_at=dt_at(order_date, 9)))
        for n, l in enumerate(ls, start=1):
            lid += 1
            l["line_id"], l["po_id"], l["po_number"], l["line_number"] = lid, hid, f"SYN-PO-{hid:06d}", n
            pol_rows.append(dict(
                purchase_order_line_id=lid, purchase_order_id=hid, line_number=n, material_id=l["material_id"],
                ordered_quantity=l["ordered"] / 1000, received_quantity=sum(q for _, q in l["receipts"]) / 1000,
                unit_price=l["unit_price"], expected_delivery_date=l["expected"]))
    R["purchase_orders"] = pd.DataFrame(po_rows)
    R["purchase_order_lines"] = pd.DataFrame(pol_rows)

    # inventory rows + transactions
    inv_id = {}
    for wh in wh_ids:
        for mid in mat_ids:
            inv_id[(wh, mid)] = len(inv_id) + 1
    tx = []  # (ts, prio, ordinal, row)
    for (wh, mid), led in ledgers.items():
        iid = inv_id[(wh, mid)]
        tx.append((hist_start_ts(ctx), 0, iid, dict(
            inventory_id=iid, transaction_type="Opening Balance", quantity_delta=led.opening / 1000, occurred_at=hist_start_ts(ctx),
            project_id=None, requirement_line_id=None, allocation_id=None, purchase_order_line_id=None,
            recorded_by_user_id=None, reference_code=f"OB-{iid:05d}",
            notes="SYNTHETIC opening balance (seed data).")))
    for l in po_lines:
        for k, (ts, q) in enumerate(l["receipts"], start=1):
            iid = inv_id[(l["wh"], l["material_id"])]
            tx.append((ts, 1, l["line_id"] * 10 + k, dict(
                inventory_id=iid, transaction_type="Receipt", quantity_delta=q / 1000, occurred_at=ts, project_id=None,
                requirement_line_id=None, allocation_id=None, purchase_order_line_id=l["line_id"],
                recorded_by_user_id=int(rng.choice(inv_mgrs)), reference_code=f"GRN-{l['line_id']:06d}-{k}",
                notes=f"SYNTHETIC receipt against {l['po_number']} line {l['line_number']}.")))
    for p in pieces:
        iid = inv_id[(p["wh"], p["material_id"])]
        for k, (ts, q) in enumerate(p["cons"], start=1):
            tx.append((ts, 2, p["id"] * 10 + k, dict(
                inventory_id=iid, transaction_type="Consumption", quantity_delta=-q / 1000, occurred_at=ts,
                project_id=p["project_id"], requirement_line_id=p["line_id"], allocation_id=p["id"],
                purchase_order_line_id=None, recorded_by_user_id=int(rng.choice(inv_mgrs)),
                reference_code=f"ISS-{p['id']:06d}-{k}", notes="SYNTHETIC consumption issued to project.")))
    tx.sort(key=lambda t: (t[0], t[1], t[2]))
    rows = []
    for n, (_, _, _, row) in enumerate(tx, start=1):
        rows.append(dict(row, inventory_transaction_id=n, created_at=row["occurred_at"]))
    R["inventory_transactions"] = pd.DataFrame(rows)

    # inventory (on-hand derived from transactions) + synthetic stock parameters
    tdf = R["inventory_transactions"]
    on_hand = (tdf.assign(m=np.rint(tdf.quantity_delta * 1000).astype("int64")).groupby("inventory_id").m.sum()).to_dict()
    last_ts = tdf.groupby("inventory_id").occurred_at.max().to_dict()
    inv_rows = []
    for (wh, mid), iid in inv_id.items():
        safety, rop, _up_to = params[(wh, mid)]
        inv_rows.append(dict(inventory_id=iid, warehouse_id=wh, material_id=mid, on_hand_quantity=on_hand[iid] / 1000,
                             safety_stock_quantity=safety / 1000, reorder_point_quantity=rop / 1000,
                             updated_at=last_ts[iid]))
    R["inventory"] = pd.DataFrame(inv_rows)


def hist_start_ts(ctx):
    return dt_at(ctx["hist_start"], 0, 0)


# --------------------------------------------------------------------------------------
# Typing / output
# --------------------------------------------------------------------------------------
def coerce(name: str, df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=range(len(df)))
    for col, typ in SCHEMA[name]:
        s = df[col].reset_index(drop=True)
        if typ in ("BIGINT", "INTEGER"):
            out[col] = pd.to_numeric(s).astype("Int64")
        elif typ.startswith("NUMERIC"):
            out[col] = pd.to_numeric(s).astype("float64")
        elif typ == "BOOLEAN":
            out[col] = s.astype("boolean")
        else:
            out[col] = s.astype(object)
    return out


def _isnull(v):
    return v is None or v is pd.NaT or (not isinstance(v, (str, datetime, date)) and pd.isna(v))


def to_csv_frame(name: str, typed: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=typed.index)
    for col, typ in SCHEMA[name]:
        s = typed[col]
        if typ in ("BIGINT", "INTEGER"):
            out[col] = s
        elif typ == "BOOLEAN":
            out[col] = s.map(lambda v: "" if pd.isna(v) else ("true" if v else "false"))
        elif typ in ("DATE", "TIMESTAMPTZ"):
            out[col] = s.map(lambda v: "" if _isnull(v) else v.isoformat())
        elif typ.startswith("NUMERIC"):
            dec = int(re.search(r",(\d+)\)", typ).group(1))
            out[col] = s.map(lambda v, d=dec: "" if pd.isna(v) else f"{float(v):.{d}f}")
        else:
            out[col] = s.map(lambda v: "" if _isnull(v) else str(v))
    return out


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------
def mi(series) -> pd.Series:
    return np.rint(series.astype("float64") * 1000).astype("int64")


def validate(cfg, T, catalogue, ctx):
    passed, errors = [], []

    def check(name, cond, detail=""):
        if bool(cond):
            passed.append(name)
        else:
            errors.append(f"{name}{': ' + detail if detail else ''}")

    as_of = ctx["as_of"]
    for t in IMPORT_ORDER:
        pk = SCHEMA[t][0][0]
        check(f"{t}: primary key unique, positive, non-null", T[t][pk].notna().all() and T[t][pk].is_unique and (T[t][pk] > 0).all())
    for t, fks in FOREIGN_KEYS.items():
        for col, parent, pcol in fks:
            vals = T[t][col].dropna()
            check(f"FK {t}.{col} -> {parent}.{pcol}", vals.isin(T[parent][pcol]).all(),
                  f"{(~vals.isin(T[parent][pcol])).sum()} orphan rows")
    for t, c in [("departments", "department_code"), ("roles", "role_code"), ("users", "employee_id"), ("users", "email"),
                 ("project_categories", "category_code"), ("material_categories", "category_code"),
                 ("units_of_measure", "uom_code"), ("materials", "material_code"), ("warehouses", "warehouse_code"),
                 ("suppliers", "supplier_code"), ("projects", "project_code"), ("purchase_orders", "po_number"),
                 ("inventory_transactions", "reference_code")]:
        check(f"{t}.{c} unique", T[t][c].is_unique)

    # catalogue fidelity
    M = T["materials"]
    cat_codes = [m["code"] for m in catalogue]
    check("materials == catalogue (codes, order)", M.material_code.tolist() == cat_codes)
    uom_map = dict(zip(T["units_of_measure"].uom_id, T["units_of_measure"].uom_code))
    check("materials units == catalogue units", [uom_map[u] for u in M.base_uom_id] == [m["uom"] for m in catalogue])
    check("materials names == catalogue names", M.name.tolist() == [m["name"] for m in catalogue])

    # users
    U = T["users"]
    admin_id = T["roles"].loc[T["roles"].role_code == "ADMIN", "role_id"].iloc[0]
    check("users: all Disabled with no usable credentials", (U.account_status == "Disabled").all() and (U.password_hash == NO_LOGIN_HASH).all())
    check("users: reserved example.invalid emails", U.email.str.endswith("@example.invalid").all())
    check("users: no generated ADMIN", not ((U.requested_role_id == admin_id) | (U.assigned_role_id == admin_id)).any())

    # rules
    RL = T["project_category_material_rules"]
    check("rules: one row per category/material/band", not RL.duplicated(["project_category_id", "material_id", "scale_band"]).any())
    cand = {}
    cname_to_id = dict(zip(T["project_categories"].name, T["project_categories"].project_category_id))
    for i, m in enumerate(catalogue, start=1):
        for c in m["candidates"]:
            cand.setdefault(cname_to_id[c], set()).add(i)
    ok_rules = all(set(g.material_id) == cand[cid] for cid, g in RL.groupby("project_category_id"))
    check("rules: materials == catalogue candidates for each category", ok_rules)
    check("rules: positive base quantity, valid bands", (RL.base_quantity >= 0).all() and RL.scale_band.isin(["all"] + [b.lower() for b in cfg["furnace_bands"]]).all())

    # projects / versions / lines
    P, V, L = T["projects"], T["project_requirement_versions"], T["project_material_requirements"]
    check("projects: only Active/Completed generated", P.status.isin(["Active", "Completed"]).all())
    check("projects: completed per category == config",
          (P[P.status == "Completed"].groupby("project_category_id").size() == cfg["completed_projects_per_category"]).all()
          and P[P.status == "Completed"].project_category_id.nunique() == len(CATEGORIES))
    act = P[P.status == "Active"]
    check("projects: >=1 active per category", act.project_category_id.nunique() == len(CATEGORIES))
    if not cfg.get("active_projects_by_category"):
        check("projects: active count == config", len(act) == cfg["active_projects"])
    check("projects: dates consistent", (P.start_date <= P.end_date).all()
          and (P[P.status == "Completed"].end_date < as_of).all()
          and ((act.start_date <= as_of) & (act.end_date > as_of)).all())
    kind_by_cat = dict(zip(T["project_categories"].project_category_id, T["project_categories"].scale_kind))
    kinds = P.project_category_id.map(kind_by_cat)
    check("projects: scale fields match category",
          (((kinds == "ORDINAL_BAND") & P.scale_level.notna() & P.scale_value.isna() & P.equipment_count.isna())
           | ((kinds != "ORDINAL_BAND") & P.scale_level.isna() & P.scale_value.notna())).all()
          and (P.equipment_count.notna() == (kinds == "EQUIPMENT_COUNT")).all())
    check("versions: one Approved version per project", (V.review_status == "Approved").all() and V.project_id.is_unique)
    check("versions: no fabricated forecast metadata", L.confidence_score.isna().all() and (V.prediction_method == "SYNTHETIC_RULE_BASELINE").all())
    LL = L.merge(V[["requirement_version_id", "project_id"]], on="requirement_version_id").merge(
        P[["project_id", "project_category_id", "start_date", "end_date"]], on="project_id")
    check("lines: materials allowed for project category", all(m in cand[c] for c, m in zip(LL.project_category_id, LL.material_id)))
    check("lines: quantities positive", (L.predicted_quantity > 0).all() and (L.proposed_quantity > 0).all() and (L.approved_quantity > 0).all())
    check("lines: need_by within project window", ((LL.need_by_date >= LL.start_date) & (LL.need_by_date <= LL.end_date)).all())
    check("lines: unique line_number per version", not L.duplicated(["requirement_version_id", "line_number"]).any())
    uoms = dict(zip(M.material_id, [uom_map[u] for u in M.base_uom_id]))
    check("lines: 'ea' quantities are whole numbers",
          all(float(q).is_integer() for m, q in zip(L.material_id, L.approved_quantity) if uoms[m] == "ea"))

    # inventory + transactions
    I, A, X = T["inventory"], T["inventory_allocations"], T["inventory_transactions"]
    check("inventory: one row per warehouse/material", not I.duplicated(["warehouse_id", "material_id"]).any()
          and len(I) == len(T["warehouses"]) * len(M))
    check("inventory: quantities >= 0", (I.on_hand_quantity >= 0).all() and (I.safety_stock_quantity >= 0).all() and (I.reorder_point_quantity >= 0).all())
    opening = X[X.transaction_type == "Opening Balance"]
    check("transactions: exactly one opening balance per inventory row", opening.inventory_id.is_unique and set(opening.inventory_id) == set(I.inventory_id) and (opening.quantity_delta > 0).all())
    sums = X.assign(m=mi(X.quantity_delta)).groupby("inventory_id").m.sum()
    check("inventory.on_hand == opening + sum(deltas)", (mi(I.set_index("inventory_id").on_hand_quantity) == sums.reindex(I.inventory_id).values).all())
    Xs = X.sort_values("inventory_transaction_id").assign(m=mi(X.sort_values("inventory_transaction_id").quantity_delta))
    check("transactions: running on-hand never negative", (Xs.groupby("inventory_id").m.cumsum() >= 0).all())
    check("transactions: type/sign rules", ((X.transaction_type == "Consumption") == (X.quantity_delta < 0)).all()
          and X.transaction_type.isin(["Opening Balance", "Receipt", "Consumption"]).all())
    check("transactions: ids chronological", pd.to_datetime(Xs.occurred_at, utc=True).is_monotonic_increasing)
    check("transactions: not after as-of date", (pd.to_datetime(X.occurred_at, utc=True) < pd.Timestamp(as_of + timedelta(days=1), tz="UTC")).all())

    # allocations
    A2 = A.merge(L[["requirement_line_id", "material_id", "approved_quantity", "requirement_version_id"]], on="requirement_line_id", suffixes=("", "_req"))
    check("allocations: positive", (A.allocated_quantity > 0).all())
    check("allocations: sum per line <= approved quantity",
          (mi(A.groupby("requirement_line_id").allocated_quantity.sum()) <= mi(L.set_index("requirement_line_id").approved_quantity.reindex(
              A.groupby("requirement_line_id").allocated_quantity.sum().index))).all())
    cons = X[X.transaction_type == "Consumption"]
    cons_by_alloc = (-mi(cons.quantity_delta)).groupby(cons.allocation_id).sum()
    A2["consumed"] = A2.allocation_id.map(cons_by_alloc).fillna(0).astype("int64")
    A2["alloc_m"] = mi(A2.allocated_quantity)
    check("allocations: consumption <= allocation", (A2.consumed <= A2.alloc_m).all())
    check("allocations: status consistent",
          ((A2.allocation_status == "Consumed") == (A2.consumed == A2.alloc_m)).all()
          and (A2[A2.allocation_status == "Released"].released_at.notna().all())
          and (A2[A2.allocation_status != "Released"].released_at.isna().all()))
    check("consumption tx: allocation, line, project, inventory row agree",
          cons.merge(A2[["allocation_id", "requirement_line_id", "warehouse_id", "material_id"]], on="allocation_id", suffixes=("", "_a"))
          .merge(I[["inventory_id", "warehouse_id", "material_id"]], on="inventory_id", suffixes=("", "_i"))
          .eval("(requirement_line_id == requirement_line_id_a) & (warehouse_id == warehouse_id_i) & (material_id == material_id_i)").all()
          and cons.project_id.notna().all())
    proj_of_line = LL.set_index("requirement_line_id").project_id
    check("consumption tx: project matches requirement line", (cons.project_id.values == proj_of_line.reindex(cons.requirement_line_id).values).all())
    out = A2[A2.allocation_status == "Active"].assign(o=lambda d: d.alloc_m - d.consumed).groupby(["warehouse_id", "material_id"]).o.sum()
    on_hand = I.set_index(["warehouse_id", "material_id"]).on_hand_quantity
    check("allocations: outstanding <= physical on-hand", (out <= mi(on_hand.reindex(out.index))).all())
    avail = mi(on_hand) - out.reindex(on_hand.index).fillna(0).astype("int64")
    stats = {"scenario": "stress" if cfg["stress"]["enabled"] else "baseline", "inventory_rows": int(len(I)), "rows_available_at_or_below_reorder_point": int(
        (avail <= mi(I.set_index(["warehouse_id", "material_id"]).reorder_point_quantity)).sum())}
    check("project status vs allocations: completed projects hold no Active allocations",
          not A2.merge(LL[["requirement_line_id", "project_id"]], on="requirement_line_id").merge(P[["project_id", "status"]], on="project_id")
          .query("status == 'Completed' and allocation_status == 'Active'").shape[0])

    # replay "available stock" (on-hand minus reservations) through time
    ev = []
    pos = X[X.transaction_type != "Consumption"]
    ev.append(pd.DataFrame(dict(inv=pos.inventory_id, ts=pd.to_datetime(pos.occurred_at, utc=True), prio=0, d=mi(pos.quantity_delta))))
    A3 = A2.merge(I[["inventory_id", "warehouse_id", "material_id"]], on=["warehouse_id", "material_id"])
    ev.append(pd.DataFrame(dict(inv=A3.inventory_id, ts=pd.to_datetime(A3.allocated_at, utc=True), prio=1, d=-A3.alloc_m)))
    rel = A3[A3.allocation_status == "Released"]
    ev.append(pd.DataFrame(dict(inv=rel.inventory_id, ts=pd.to_datetime(rel.released_at, utc=True), prio=0, d=rel.alloc_m - rel.consumed)))
    E = pd.concat(ev).sort_values(["inv", "ts", "prio"])
    check("allocations never exceed available stock at any point in time", (E.groupby("inv").d.cumsum() >= 0).all())

    # purchase orders
    PO, PL = T["purchase_orders"], T["purchase_order_lines"]
    rec = X[X.transaction_type == "Receipt"]
    rec_by_line = mi(rec.quantity_delta).groupby(rec.purchase_order_line_id).sum()
    PLm = PL.assign(rm=mi(PL.received_quantity), om=mi(PL.ordered_quantity))
    check("PO lines: no over-receipt, quantities valid", (PLm.rm <= PLm.om).all() and (PLm.om > 0).all() and (PL.unit_price > 0).all())
    check("PO lines: received == sum of receipt transactions", (PLm.set_index("purchase_order_line_id").rm.values
          == rec_by_line.reindex(PL.purchase_order_line_id).fillna(0).astype("int64").values).all())
    rj = rec.merge(PL[["purchase_order_line_id", "purchase_order_id", "material_id"]], on="purchase_order_line_id", suffixes=("", "_l")) \
            .merge(PO[["purchase_order_id", "warehouse_id", "order_date"]], on="purchase_order_id") \
            .merge(I[["inventory_id", "warehouse_id", "material_id"]], on="inventory_id", suffixes=("", "_i"))
    check("receipts link to correct PO line (material, warehouse)", len(rj) == len(rec)
          and (rj.material_id == rj.material_id_i).all() and (rj.warehouse_id == rj.warehouse_id_i).all())
    check("receipts not before order date", (pd.to_datetime(rj.occurred_at, utc=True).dt.date >= rj.order_date).all())
    check("PO dates consistent", (PO.expected_delivery_date >= PO.order_date).all()
          and (PO.dropna(subset=["actual_delivery_date"]).actual_delivery_date >= PO.dropna(subset=["actual_delivery_date"]).order_date).all())
    pl_full = PLm.groupby("purchase_order_id").apply(lambda g: (g.rm == g.om).all(), include_groups=False)
    check("PO status consistent with lines", (PO.set_index("purchase_order_id").status.eq("Received") == pl_full.reindex(PO.purchase_order_id).values).all())
    check("PO lines: line_number unique per PO", not PL.duplicated(["purchase_order_id", "line_number"]).any())
    ms = T["material_suppliers"]
    check("material_suppliers: every material has a preferred supplier", ms[ms.is_preferred].material_id.nunique() == len(M))
    check("material_suppliers: PO supplier supplies the material",
          PL.merge(PO[["purchase_order_id", "supplier_id"]], on="purchase_order_id")[["supplier_id", "material_id"]]
          .merge(ms[["supplier_id", "material_id"]].drop_duplicates(), how="left", indicator=True)._merge.eq("both").all())

    if errors:
        raise SystemExit("DATA INTEGRITY VALIDATION FAILED:\n  - " + "\n  - ".join(errors))
    return passed, stats


# --------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------
def run(cfg):
    catalogue = parse_catalogue(cfg["catalogue_path"])
    validate_config(cfg, catalogue)
    as_of = date.fromisoformat(cfg["as_of_date"])
    ctx = {"as_of": as_of, "hist_start": shift_years(as_of, -int(cfg["history_years"]))}
    R = build_masters(cfg, catalogue, ctx)
    build_projects(cfg, catalogue, R, ctx)
    build_operations(cfg, catalogue, R, ctx)
    T = {name: coerce(name, R[name]) for name in IMPORT_ORDER}
    passed, stats = validate(cfg, T, catalogue, ctx)

    out_dir = Path(cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = {}
    for name in IMPORT_ORDER:
        path = out_dir / f"{name}.csv"
        to_csv_frame(name, T[name]).to_csv(path, index=False, lineterminator="\n", encoding="utf-8")
        bad = pd.read_csv(path, dtype=str, keep_default_na=False).isin(["NaT", "nan", "NaN", "<NA>", "None"]).any().any()
        if bad:
            raise SystemExit(f"{path.name}: found a null placeholder text (NaT/nan/None) in the output")
        tables[name] = {"file": path.name, "row_count": int(len(T[name])),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "columns": [{"name": c, "type": t} for c, t in SCHEMA[name]]}
    manifest = {
        "synthetic_data_label": SYNTHETIC_LABEL, "is_synthetic": True,
        "generator": "generate_dataset.py", "generator_version": GENERATOR_VERSION,
        "seed": cfg["seed"], "as_of_date": cfg["as_of_date"], "configuration": cfg, "import_order": IMPORT_ORDER,
        "tables": tables,
        "validation": {"status": "passed", "checks_passed": len(passed), "checks": passed},
        "statistics": stats,
        "environment": {"python": sys.version.split()[0], "pandas": pd.__version__, "numpy": np.__version__},
        "notes": [
            "Opening balances, safety stock and reorder points are synthetic values computed by the generator, not LLM-invented.",
            "predicted_quantity is a deterministic synthetic rule baseline, not an ML forecast; confidence_score is intentionally NULL.",
            "No forecast outputs, risk alerts, anomaly outputs or procurement recommendations are generated.",
            "Generated users are disabled and have no usable credentials; no admin account is created.",
        ],
    }
    (out_dir / "generation_manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")

    print(f"SYNTHETIC dataset v{GENERATOR_VERSION} written to {out_dir}/  (seed={cfg['seed']}, as_of={cfg['as_of_date']})")
    for name in IMPORT_ORDER:
        print(f"  {name:<34}{len(T[name]):>7}")
    print(f"Stock rows with available <= reorder point: {stats['rows_available_at_or_below_reorder_point']} of {stats['inventory_rows']}")
    print(f"Validation: {len(passed)} integrity checks passed. Manifest: {out_dir / 'generation_manifest.json'}")


def main():
    ap = argparse.ArgumentParser(description="Generate deterministic SYNTHETIC CSV seed data.")
    ap.add_argument("--config", help="JSON config file overriding the defaults")
    ap.add_argument("--catalogue", help="Path to the material catalogue markdown file")
    ap.add_argument("--output-dir", help="Override output directory (default data/generated/v1)")
    ap.add_argument("--stress", action="store_true", help="enable the stress demo scenario (thin stock, more open orders)")
    ap.add_argument("--dump-default-config", metavar="PATH", help="Write the full default config to PATH and exit")
    args = ap.parse_args()
    if args.dump_default_config:
        Path(args.dump_default_config).write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
        print(f"Default configuration written to {args.dump_default_config}")
        return
    cfg = load_config(args.config)
    if args.catalogue:
        cfg["catalogue_path"] = args.catalogue
    if args.output_dir:
        cfg["output_dir"] = args.output_dir
    if args.stress:
        cfg["stress"]["enabled"] = True
    run(cfg)


if __name__ == "__main__":
    main()
