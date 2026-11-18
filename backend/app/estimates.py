"""
Quantity-estimate endpoints (read-only). All data and estimates are SYNTHETIC.

Serves the per-material scale model saved by ml/train_quantity_model.py
(ml/artifacts/quantity_model_v1.json). Pure Python: no pandas / scikit-learn needed here.
Nothing is stored: a preview is a calculation, not an approved requirement. Estimates are
fictional assumptions, not engineering recommendations or an approved bill of materials.

Set QUANTITY_MODEL_PATH to use a model file somewhere else. The file is re-read when it changes,
so retraining the model does not require restarting the API.
"""
import json
import os
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from . import db
from .common import SYNTHETIC_NOTICE

router = APIRouter(prefix="/api/estimates", tags=["estimates"])
Cursor = Depends(db.get_cursor)

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # .../Internship Project (backend/app/estimates.py)
MODEL_PATH = Path(os.getenv("QUANTITY_MODEL_PATH") or PROJECT_ROOT / "ml" / "artifacts" / "quantity_model_v1.json")
FURNACE = "BLAST_FURNACE_UPGRADE"
BAND_RANK = {"Small": 0, "Medium": 1, "Large": 2}
DECIMALS = {"ea": 0, "kg": 0, "m": 1, "L": 0}  # same as the generator / training script

_cache = {"mtime": None, "model": None, "metrics": None}


def get_model() -> dict:
    path = Path(os.getenv("QUANTITY_MODEL_PATH") or MODEL_PATH)
    if not path.exists():
        raise HTTPException(503, f"Quantity model not found at {path}. Run ml/train_quantity_model.py first.")
    mtime = path.stat().st_mtime
    if _cache["mtime"] != mtime:
        _cache["model"] = json.loads(path.read_text(encoding="utf-8"))
        metrics_path = path.with_name("quantity_model_metrics.json")
        _cache["metrics"] = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else None
        _cache["mtime"] = mtime
    return _cache["model"]


# ------------------------------------------------------------------ model maths (mirrors the training script)
def round_qty(x: float, uom: str) -> float:
    dec = DECIMALS[uom]
    step = 10 ** -dec
    return round(max(step, round(x / step) * step), dec)


def _interp(x: float, xs: list, ys: list) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / (xs[i] - xs[i - 1])
    return ys[-1]


def raw_estimate(model: dict, category: str, material_id: int, x: float) -> Optional[float]:
    c = model["coefficients"].get(f"{category}|{material_id}")
    if c is None:
        return None
    return _interp(x, c["x"], c["y"]) if c["type"] == "band_mean" else c["a"] + c["b"] * x


def scale_to_x(model: dict, category: str, level: Optional[str], value: Optional[float]) -> float:
    if category not in model["scale_ranges"]:
        raise HTTPException(404, f"Unknown category '{category}'. Valid: {sorted(model['scale_ranges'])}")
    if category == FURNACE:
        if level not in BAND_RANK:
            raise HTTPException(422, "BLAST_FURNACE_UPGRADE needs scale_level = Small, Medium or Large.")
        return float(BAND_RANK[level])
    if value is None or value <= 0:
        raise HTTPException(422, f"{category} needs a positive scale_value (metres, equipment count or kW).")
    return float(value)


def estimate_lines(model: dict, category: str, x: float) -> list:
    iv = model["intervals"].get(category, {"p10": 1.0, "p90": 1.0})
    lo, hi = model["scale_ranges"][category]
    extrapolated = not (lo <= x <= hi)
    out = []
    for mid, info in sorted(model["materials"].items(), key=lambda kv: int(kv[0])):
        raw = raw_estimate(model, category, int(mid), x)
        if raw is None:
            continue
        q = round_qty(max(raw, 0.0), info["uom"])
        out.append({"material_id": int(mid), "material_code": info["code"], "uom_code": info["uom"], "estimated_quantity": q,
                    "range_p10": round_qty(q * iv["p10"], info["uom"]), "range_p90": round_qty(q * iv["p90"], info["uom"]),
                    "extrapolated_scale": extrapolated})
    return out


def _enrich(cur, lines: list) -> None:
    """Add material name and preferred-supplier price / lead time (synthetic) to estimate lines."""
    cur.execute("""SELECT m.material_code, m.name, ms.unit_price, ms.currency_code, ms.lead_time_days
                   FROM materials m LEFT JOIN material_suppliers ms ON ms.material_id = m.material_id AND ms.is_preferred
                   WHERE m.material_code = ANY(%s)""", ([l["material_code"] for l in lines],))
    info = {r["material_code"]: r for r in cur.fetchall()}
    for l in lines:
        r = info.get(l["material_code"], {})
        l["material_name"] = r.get("name")
        price = float(r["unit_price"]) if r.get("unit_price") is not None else None
        l["unit_price"], l["currency_code"], l["preferred_lead_time_days"] = price, r.get("currency_code"), r.get("lead_time_days")
        l["indicative_value"] = round(price * l["estimated_quantity"], 2) if price is not None else None


def _model_summary(model: dict) -> dict:
    cv = ((_cache["metrics"] or {}).get("cross_validation") or {}).get("scale_model")
    return {"version": model["model_version"], "type": model["model_type"], "target": model["target"],
            "trained_on": model["trained_on"], "interval_note": model["interval_note"],
            "cross_validated_mean_error": cv["mean_ape"]["mean"] if cv else None,
            "cross_validated_within_20pct": cv["within_20pct"]["mean"] if cv else None}


# ------------------------------------------------------------------ endpoints
@router.get("/model")
def model_info(cur=Cursor):
    """Model version, training size, accuracy summary and the categories / scale ranges it supports."""
    model = get_model()
    cur.execute("SELECT category_code, name, scale_kind, scale_unit FROM project_categories ORDER BY project_category_id")
    cats = []
    for r in cur.fetchall():
        if r["category_code"] in model["scale_ranges"]:
            lo, hi = model["scale_ranges"][r["category_code"]]
            cats.append({**r, "training_scale_range": ["Small", "Large"] if r["category_code"] == FURNACE else [lo, hi],
                         "allowed_scale_levels": list(BAND_RANK) if r["category_code"] == FURNACE else None,
                         "empirical_range_factors": model["intervals"].get(r["category_code"])})
    return {"notice": SYNTHETIC_NOTICE, "synthetic_label": model["synthetic_label"], "model": _model_summary(model),
            "limitations": ["Trained on a small synthetic dataset; accuracy figures do not transfer to real projects.",
                            "Estimates outside the training scale range are flagged extrapolated_scale and should not be trusted."],
            "categories": cats}


@router.get("/preview")
def preview_estimate(category_code: str,
                     scale_level: Optional[Literal["Small", "Medium", "Large"]] = Query(None, description="furnace upgrades only"),
                     scale_value: Optional[float] = Query(None, gt=0, description="metres / equipment count / kW"),
                     cur=Cursor):
    """Estimate material quantities for a NEW project from its category and scale. Not stored or approved."""
    model = get_model()
    x = scale_to_x(model, category_code, scale_level, scale_value)
    lines = estimate_lines(model, category_code, x)
    _enrich(cur, lines)
    values = [l["indicative_value"] for l in lines if l["indicative_value"] is not None]
    return {"notice": SYNTHETIC_NOTICE, "model": _model_summary(model),
            "input": {"category_code": category_code, "scale_level": scale_level if category_code == FURNACE else None,
                      "scale_value": scale_value if category_code != FURNACE else None},
            "extrapolated": any(l["extrapolated_scale"] for l in lines),
            "line_count": len(lines), "indicative_total_value": round(sum(values), 2) if values else None,
            "value_note": "Point estimates x synthetic preferred-supplier prices. p10-p90 ranges are per line and are not summed.",
            "lines": lines}


@router.get("/compare/{project_id}")
def compare_with_project(project_id: int, cur=Cursor):
    """Model estimate vs the APPROVED quantities of an existing project (demo / sanity check).
    For Completed projects the model was trained on them, so the comparison is in-sample."""
    model = get_model()
    cur.execute("""SELECT p.project_code, p.status, pc.category_code, p.scale_level, p.scale_value
                   FROM projects p JOIN project_categories pc ON pc.project_category_id = p.project_category_id
                   WHERE p.project_id = %s""", (project_id,))
    p = cur.fetchone()
    if not p:
        raise HTTPException(404, "Project not found")
    cur.execute("""SELECT r.line_number, m.material_code, r.approved_quantity
                   FROM project_requirement_versions v
                   JOIN project_material_requirements r ON r.requirement_version_id = v.requirement_version_id
                   JOIN materials m ON m.material_id = r.material_id
                   WHERE v.project_id = %(p)s AND v.review_status = 'Approved'
                     AND v.version_number = (SELECT MAX(v2.version_number) FROM project_requirement_versions v2
                                             WHERE v2.project_id = %(p)s AND v2.review_status = 'Approved')
                   ORDER BY r.line_number""", dict(p=project_id))
    approved = {r["material_code"]: float(r["approved_quantity"]) for r in cur.fetchall()}
    if not approved:
        raise HTTPException(409, "Project has no approved requirement lines to compare against.")
    x = scale_to_x(model, p["category_code"], p["scale_level"], float(p["scale_value"]) if p["scale_value"] is not None else None)
    lines = estimate_lines(model, p["category_code"], x)
    _enrich(cur, lines)
    out, within, errs = [], 0, []
    for l in lines:
        a = approved.get(l["material_code"])
        if a is None:
            continue
        err = abs(l["estimated_quantity"] - a) / a
        inside = l["range_p10"] <= a <= l["range_p90"]
        within += inside
        errs.append(err)
        out.append({"material_code": l["material_code"], "material_name": l["material_name"], "uom_code": l["uom_code"],
                    "estimated_quantity": l["estimated_quantity"], "range_p10": l["range_p10"], "range_p90": l["range_p90"],
                    "approved_quantity": a, "difference_pct": round((l["estimated_quantity"] - a) / a * 100, 1), "approved_within_range": inside})
    return {"notice": SYNTHETIC_NOTICE, "project_code": p["project_code"], "project_status": p["status"],
            "in_sample": p["status"] == "Completed",
            "in_sample_note": "The model was trained on completed projects, so this comparison flatters it." if p["status"] == "Completed" else None,
            "lines_compared": len(out), "mean_abs_error_pct": round(sum(errs) / len(errs) * 100, 1) if errs else None,
            "share_within_range": round(within / len(out), 3) if out else None, "lines": out}
