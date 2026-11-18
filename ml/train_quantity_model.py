#!/usr/bin/env python3
"""
train_quantity_model.py - learn material-quantity estimates from COMPLETED synthetic projects.

*** SYNTHETIC DATA ***  Results describe a fictional, tiny dataset. They are NOT evidence of
real-world accuracy and the output is NOT an engineering recommendation or approved BOM.

What it does
  1. loads completed projects' approved requirement lines (CSV files or PostgreSQL)
  2. evaluates four approaches with PROJECT-LEVEL splits (a project's lines never straddle
     train and test): repeated grouped cross-validation + a time-ordered holdout
        naive_median   median quantity per (category, material), ignores scale
        rule_baseline  the stored predicted_quantity (synthetic rule value) - NOT learned, not a feature
        scale_model    per (category, material) linear fit on scale (furnace: mean per band)
        gbm            gradient boosting on log quantity (category, material, scale)
  3. fits the scale_model on all completed projects and saves it as plain JSON
     (artifacts/quantity_model_v1.json) with empirical p10/p90 ranges from out-of-fold ratios

Leakage guards: features are category, material, scale only. approved_quantity is the target.
predicted_quantity / proposed_quantity, allocations, consumption and receipts are never features.
Active projects are never used (their requirements are not yet history).

Usage
    python train_quantity_model.py                         # reads ../data/generated/v1/*.csv
    python train_quantity_model.py --source db             # reads PostgreSQL (uses .env)
    python train_quantity_model.py --demo-category CONVEYOR_SYSTEM_INSTALLATION --demo-scale 1500
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_VERSION = "1.0.0"
HERE = Path(__file__).resolve().parent  # defaults are relative to this script, not the terminal's folder
SYNTHETIC_LABEL = ("SYNTHETIC DATA. Fictional prototype; estimates are not engineering recommendations "
                   "or an approved bill of materials.")
FURNACE = "BLAST_FURNACE_UPGRADE"
BAND_RANK = {"Small": 0, "Medium": 1, "Large": 2}
DECIMALS = {"ea": 0, "kg": 0, "m": 1, "L": 0}  # must match the generator's quantity_decimals


# ----------------------------------------------------------------------------- data loading
def load_frame(source: str, data_dir: Path, env_file: Path | None):
    if source == "csv":
        rd = lambda n: pd.read_csv(data_dir / f"{n}.csv")
        p, pc, d = rd("projects"), rd("project_categories"), rd("departments")
        v, r, m, u, ms = (rd("project_requirement_versions"), rd("project_material_requirements"), rd("materials"),
                          rd("units_of_measure"), rd("material_suppliers"))
        df = (p[p.status == "Completed"]
              .merge(pc[["project_category_id", "category_code"]], on="project_category_id")
              .merge(d[["department_id", "name"]].rename(columns={"name": "department"}), on="department_id")
              .merge(v[v.review_status == "Approved"][["requirement_version_id", "project_id"]], on="project_id")
              .merge(r, on="requirement_version_id")
              .merge(m[["material_id", "material_code", "base_uom_id"]], on="material_id")
              .merge(u[["uom_id", "uom_code"]], left_on="base_uom_id", right_on="uom_id"))
        prices = ms[ms.is_preferred].set_index("material_id").unit_price.to_dict()
    else:
        import psycopg2
        from dotenv import load_dotenv
        load_dotenv(env_file) if env_file and env_file.exists() else load_dotenv()
        conn = psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                                dbname=os.getenv("DB_NAME", "inventory_db"), user=os.getenv("DB_USER", "postgres"),
                                password=os.getenv("DB_PASSWORD") or os.getenv("PGPASSWORD"),
                                options="-c default_transaction_read_only=on")
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT p.project_id, p.project_code, p.start_date, pc.category_code, p.scale_level, p.scale_value,
                       d.name AS department, m.material_id, m.material_code, u.uom_code,
                       r.predicted_quantity, r.proposed_quantity, r.approved_quantity
                FROM projects p
                JOIN project_categories pc ON pc.project_category_id = p.project_category_id
                JOIN departments d ON d.department_id = p.department_id
                JOIN project_requirement_versions v ON v.project_id = p.project_id AND v.review_status = 'Approved'
                JOIN project_material_requirements r ON r.requirement_version_id = v.requirement_version_id
                JOIN materials m ON m.material_id = r.material_id
                JOIN units_of_measure u ON u.uom_id = m.base_uom_id
                WHERE p.status = 'Completed'""")
            cols = [c.name for c in cur.description]
            df = pd.DataFrame(cur.fetchall(), columns=cols)
            cur.execute("SELECT material_id, unit_price FROM material_suppliers WHERE is_preferred")
            prices = {a: float(b) for a, b in cur.fetchall()}
        conn.close()
    df["start_date"] = pd.to_datetime(df["start_date"])
    for c in ("predicted_quantity", "proposed_quantity", "approved_quantity", "scale_value"):
        df[c] = pd.to_numeric(df[c]).astype(float)
    # single numeric scale feature: band rank for furnaces, metres / items / kW otherwise
    df["scale_x"] = np.where(df.category_code == FURNACE, df.scale_level.map(BAND_RANK), df.scale_value).astype(float)
    cols = ["project_id", "project_code", "start_date", "category_code", "scale_level", "scale_value", "scale_x",
            "department", "material_id", "material_code", "uom_code", "predicted_quantity", "proposed_quantity",
            "approved_quantity"]
    return df[cols].sort_values(["project_id", "material_id"]).reset_index(drop=True), {int(k): float(v) for k, v in prices.items()}


def round_qty(x: float, uom: str) -> float:
    dec = DECIMALS[uom]
    step = 10 ** -dec
    return round(max(step, round(x / step) * step), dec)


def round_vec(pred, uoms):
    return np.array([round_qty(p, u) for p, u in zip(pred, uoms)])


# ----------------------------------------------------------------------------- models
def fit_naive(train):
    med = train.groupby(["category_code", "material_id"]).approved_quantity.median().to_dict()
    return {"med": med, "fallback": train.groupby("material_id").approved_quantity.median().to_dict()}


def predict_naive(model, df):
    out = [model["med"].get((c, m), model["fallback"].get(m, 1.0)) for c, m in zip(df.category_code, df.material_id)]
    return round_vec(out, df.uom_code)


def fit_scale(train):
    coef = {}
    for (cat, mid), g in train.groupby(["category_code", "material_id"]):
        if cat == FURNACE:
            means = g.groupby("scale_x").approved_quantity.mean()
            coef[f"{cat}|{mid}"] = {"type": "band_mean", "x": [float(i) for i in means.index], "y": [float(v) for v in means.values]}
        else:
            x, y = g.scale_x.values.astype(float), g.approved_quantity.values
            if len(np.unique(x)) >= 2:
                b, a = np.polyfit(x, y, 1)
            else:
                a, b = float(y.mean()), 0.0
            coef[f"{cat}|{mid}"] = {"type": "linear", "a": float(a), "b": float(b)}
    return coef


def raw_scale(coef, cat, mid, x):
    c = coef.get(f"{cat}|{mid}")
    if c is None:
        return np.nan
    return float(np.interp(x, c["x"], c["y"])) if c["type"] == "band_mean" else c["a"] + c["b"] * x


def predict_scale_raw(coef, df):
    return np.array([raw_scale(coef, c, m, x) for c, m, x in zip(df.category_code, df.material_id, df.scale_x)])


def predict_scale(coef, df):
    raw = predict_scale_raw(coef, df)
    raw = np.where(np.isnan(raw), 1.0, raw)
    return round_vec(raw, df.uom_code)


def _gbm_features(df, ranges):
    cats = {c: i for i, c in enumerate(sorted(ranges))}
    lo = df.category_code.map(lambda c: ranges[c][0]).values
    hi = df.category_code.map(lambda c: ranges[c][1]).values
    norm = (df.scale_x.values - lo) / np.where(hi > lo, hi - lo, 1.0)
    return np.column_stack([df.material_id.values, df.category_code.map(cats).values, norm])


def fit_gbm(train):
    from sklearn.ensemble import GradientBoostingRegressor
    ranges = {c: (g.scale_x.min(), g.scale_x.max()) for c, g in train.groupby("category_code")}
    model = GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=0)
    model.fit(_gbm_features(train, ranges), np.log(train.approved_quantity.values))
    return {"m": model, "ranges": ranges}


def predict_gbm(model, df):
    ranges = dict(model["ranges"])
    for c in df.category_code.unique():
        ranges.setdefault(c, (0.0, 1.0))
    return round_vec(np.exp(model["m"].predict(_gbm_features(df, ranges))), df.uom_code)


MODELS = {
    "naive_median": (fit_naive, predict_naive),
    "rule_baseline": (lambda tr: None, lambda m, df: df.predicted_quantity.values),
    "scale_model": (fit_scale, predict_scale),
    "gbm": (fit_gbm, predict_gbm),
}


# ----------------------------------------------------------------------------- evaluation
def metrics(df, pred, prices):
    a = df.approved_quantity.values
    err = np.abs(pred - a)
    ape = err / a
    w = df.material_id.map(prices).fillna(1.0).values
    out = {"median_ape": float(np.median(ape)), "mean_ape": float(ape.mean()),
           "within_10pct": float((ape <= 0.10).mean()), "within_20pct": float((ape <= 0.20).mean()),
           "value_weighted_ape": float((err * w).sum() / (a * w).sum())}
    out["by_category_median_ape"] = {c: float(np.median(ape[(df.category_code == c).values])) for c in sorted(df.category_code.unique())}
    return out


def grouped_oof(frame, fit, predict, n_splits, seed, repeat):
    rng = np.random.default_rng([seed, repeat])
    fold_of = {}
    for _, g in frame.groupby("category_code"):
        pids = [int(p) for p in sorted(g.project_id.unique())]
        rng.shuffle(pids)
        for i, p in enumerate(pids):
            fold_of[p] = i % n_splits
    folds = frame.project_id.map(fold_of).values
    pred = np.full(len(frame), np.nan)
    for f in range(n_splits):
        te = np.where(folds == f)[0]
        pred[te] = predict(fit(frame[folds != f]), frame.iloc[te])
    return pred


def summarize(runs):
    keys = ["median_ape", "mean_ape", "within_10pct", "within_20pct", "value_weighted_ape"]
    out = {k: {"mean": float(np.mean([r[k] for r in runs])), "std": float(np.std([r[k] for r in runs]))} for k in keys}
    cats = runs[0]["by_category_median_ape"]
    out["by_category_median_ape"] = {c: float(np.mean([r["by_category_median_ape"][c] for r in runs])) for c in cats}
    return out


def time_split(frame, per_cat):
    test_ids = []
    for _, g in frame.groupby("category_code"):
        order = g.drop_duplicates("project_id").sort_values("start_date").project_id.tolist()
        test_ids += order[-per_cat:]
    mask = frame.project_id.isin(test_ids)
    return frame[~mask], frame[mask]


# ----------------------------------------------------------------------------- prediction API
def predict_estimate(model_json: dict, category_code: str, scale_level: str | None = None, scale_value: float | None = None):
    """Estimate lines for a NEW project. Returns a list of dicts (synthetic estimates, not a BOM)."""
    x = float(BAND_RANK[scale_level]) if category_code == FURNACE else float(scale_value)
    rng_ = model_json["scale_ranges"].get(category_code)
    extrap = bool(rng_ and not (rng_[0] <= x <= rng_[1]))
    iv = model_json["intervals"].get(category_code, {"p10": 1.0, "p90": 1.0})
    lines = []
    for mid, info in sorted(model_json["materials"].items(), key=lambda kv: int(kv[0])):
        raw = raw_scale(model_json["coefficients"], category_code, int(mid), x)
        if np.isnan(raw):
            continue
        q = round_qty(max(raw, 0.0), info["uom"])
        lines.append({"material_code": info["code"], "uom": info["uom"], "estimated_quantity": q,
                      "range_p10": round_qty(q * iv["p10"], info["uom"]), "range_p90": round_qty(q * iv["p90"], info["uom"]),
                      "extrapolated_scale": extrap})
    return lines


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["csv", "db"], default="csv")
    ap.add_argument("--data-dir", default=str(HERE.parent / "data" / "generated" / "v1"))
    ap.add_argument("--env-file", default=str(HERE.parent / "backend" / ".env"))
    ap.add_argument("--out-dir", default=str(HERE / "artifacts"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--holdout-per-category", type=int, default=2)
    ap.add_argument("--demo-category")
    ap.add_argument("--demo-scale", type=float)
    ap.add_argument("--demo-level", choices=list(BAND_RANK))
    a = ap.parse_args()

    if a.source == "csv" and not (Path(a.data_dir) / "projects.csv").exists():
        sys.exit(f"Cannot find the generated CSVs in {a.data_dir}\nRun generate_dataset.py first, or pass --data-dir <folder>.")
    frame, prices = load_frame(a.source, Path(a.data_dir), Path(a.env_file))
    n_proj = frame.project_id.nunique()
    per_cat = frame.groupby("category_code").project_id.nunique().to_dict()
    print(f"Loaded {len(frame)} approved lines from {n_proj} completed projects: {per_cat}")
    if min(per_cat.values()) < a.folds:
        sys.exit(f"Need at least {a.folds} completed projects per category for {a.folds}-fold project-level CV.")
    models = {k: v for k, v in MODELS.items()}
    try:
        import sklearn  # noqa: F401
    except ImportError:
        models.pop("gbm")
        print("scikit-learn not installed: skipping gbm (pip install scikit-learn)")

    # --- repeated grouped CV
    cv, oof_scale = {}, []
    for name, (fit, predict) in models.items():
        runs = []
        for r in range(a.repeats):
            pred = grouped_oof(frame, fit, predict, a.folds, a.seed, r)
            runs.append(metrics(frame, pred, prices))
            if name == "scale_model":
                oof_scale.append(grouped_oof(frame, fit, lambda m, d: predict_scale_raw(m, d), a.folds, a.seed, r))
        cv[name] = summarize(runs)
        print(f"  CV {name:<14} median APE {cv[name]['median_ape']['mean']:.1%}  within20% {cv[name]['within_20pct']['mean']:.1%}")

    # --- time-ordered holdout
    train, test = time_split(frame, a.holdout_per_category)
    hold = {}
    for name, (fit, predict) in models.items():
        hold[name] = metrics(test, predict(fit(train), test), prices)
        print(f"  Holdout {name:<11} median APE {hold[name]['median_ape']:.1%}  within20% {hold[name]['within_20pct']:.1%}")

    # --- final model on all completed projects
    coef = fit_scale(frame)
    ratios = {}
    for cat in per_cat:
        mask = (frame.category_code == cat).values
        ar = frame.approved_quantity.values[mask]
        rs = np.concatenate([ar / np.where(o[mask] > 0, o[mask], np.nan) for o in oof_scale])
        rs = rs[np.isfinite(rs)]
        ratios[cat] = {"p10": float(np.quantile(rs, 0.10)), "p90": float(np.quantile(rs, 0.90))}
    mats = frame.drop_duplicates("material_id").set_index("material_id")
    model_json = {
        "model_version": MODEL_VERSION, "model_type": "per_material_scale_model", "synthetic_label": SYNTHETIC_LABEL,
        "trained_on": {"completed_projects": int(n_proj), "lines": int(len(frame)), "projects_per_category": per_cat},
        "features": ["category_code", "material", "scale (band rank or metres/items/kW)"],
        "target": "approved_quantity",
        "scale_ranges": {c: [float(g.scale_x.min()), float(g.scale_x.max())] for c, g in frame.groupby("category_code")},
        "intervals": ratios, "interval_note": "empirical p10/p90 of actual/estimate from out-of-fold predictions",
        "materials": {str(int(i)): {"code": r.material_code, "uom": r.uom_code} for i, r in mats.iterrows()},
        "coefficients": coef,
    }
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "quantity_model_v1.json").write_text(json.dumps(model_json, indent=2) + "\n", encoding="utf-8")
    report = {"synthetic_label": SYNTHETIC_LABEL, "model_version": MODEL_VERSION, "seed": a.seed,
              "protocol": {"cv": f"{a.folds}-fold project-level CV, stratified by category, {a.repeats} repeats",
                           "holdout": f"latest {a.holdout_per_category} projects per category by start_date",
                           "metric_note": "APE = |estimate - approved| / approved; value_weighted_ape weights by preferred-supplier unit price"},
              "cross_validation": cv, "time_holdout": hold, "holdout_projects": int(test.project_id.nunique())}
    (out / "quantity_model_metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_report(out / "quantity_model_report.md", report, per_cat)
    print(f"Saved model + metrics + report to {out}/")

    if a.demo_category:
        lines = predict_estimate(model_json, a.demo_category, a.demo_level, a.demo_scale)
        print(f"\nDEMO estimate (synthetic) for {a.demo_category}, scale={a.demo_level or a.demo_scale}:")
        for l in lines[:12]:
            print(f"  {l['material_code']:<8}{l['estimated_quantity']:>12,.1f} {l['uom']:<3} (p10-p90: {l['range_p10']:,.1f} - {l['range_p90']:,.1f})")


def write_report(path, rep, per_cat):
    cv, ho = rep["cross_validation"], rep["time_holdout"]
    f = lambda x: f"{x:.1%}"
    rows = ["| Model | Median APE | Mean APE | Within 10% | Within 20% | Value-weighted APE |", "|---|---|---|---|---|---|"]
    for n, m in cv.items():
        rows.append(f"| {n} | {f(m['median_ape']['mean'])} (+/-{f(m['median_ape']['std'])}) | {f(m['mean_ape']['mean'])} | "
                    f"{f(m['within_10pct']['mean'])} | {f(m['within_20pct']['mean'])} | {f(m['value_weighted_ape']['mean'])} |")
    hrows = ["| Model | Median APE | Mean APE | Within 10% | Within 20% | Value-weighted APE |", "|---|---|---|---|---|---|"]
    for n, m in ho.items():
        hrows.append(f"| {n} | {f(m['median_ape'])} | {f(m['mean_ape'])} | {f(m['within_10pct'])} | {f(m['within_20pct'])} | {f(m['value_weighted_ape'])} |")
    learned = {k: v["median_ape"]["mean"] for k, v in cv.items() if k not in ("rule_baseline",)}
    best = min(learned, key=learned.get)
    floor = cv["rule_baseline"]["median_ape"]["mean"]
    text = f"""# Quantity-estimate model report (v{rep['model_version']})

> {rep['synthetic_label']}

**Data:** {sum(per_cat.values())} completed projects ({per_cat}). Active projects are excluded.
**Target:** `approved_quantity` per requirement line. **Features:** category, material, scale only.

## Protocol
- {rep['protocol']['cv']}. A project's lines never appear in both train and test.
- Time holdout: {rep['protocol']['holdout']} ({rep['holdout_projects']} projects).
- APE = |estimate - approved| / approved. Value-weighted APE weights lines by preferred-supplier unit price.

## Cross-validation (mean over repeats)
{chr(10).join(rows)}

## Time-ordered holdout
{chr(10).join(hrows)}

## How to read this
- `rule_baseline` is the stored synthetic rule value. It is the noise-free centre the data was generated
  around, **not a learned model**, so its error approximates the irreducible noise: {f(cv['rule_baseline']['mean_ape']['mean'])} mean APE and
  {f(cv['rule_baseline']['value_weighted_ape']['mean'])} value-weighted APE. Its *median* APE ({f(floor)}) is near zero only because many small whole-number
  lines (for example 1 or 2 pulleys) round to exactly the same count, so prefer mean and value-weighted APE
  when comparing. No model trained on this data should be expected to beat the baseline.
- Among learned models, **{best}** has the lowest cross-validated median APE ({f(learned[best])}).
  `naive_median` ignores scale and shows how much the scale information is worth.
- The final saved model is the `scale_model` fitted on all completed projects, with empirical p10/p90
  ranges from out-of-fold actual/estimate ratios.

## Limitations (important)
- Synthetic data generated from known rules: good scores show the pipeline can recover the pattern,
  **not** that it would work on real projects.
- Only {sum(per_cat.values())} projects ({min(per_cat.values())} per category at minimum). Differences of a few percentage points are within noise.
- Small integer quantities (for example 1 vs 2 pulleys) inflate APE regardless of model quality.
- Estimates outside the training scale range are flagged `extrapolated_scale` and should not be trusted.
"""
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
