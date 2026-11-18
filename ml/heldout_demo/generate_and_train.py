"""Generate a reproducible synthetic demo dataset and train four material estimators.

These outputs are educational examples derived from fictional equations, not plant
engineering data or recommendations. See README.md before using the outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline


GENERATOR_VERSION = "synthetic-project-materials-v1"
MODEL_VERSION = "random-forest-multioutput-v1"
SEED = 20261109
PROJECTS_PER_CATEGORY = 50

# Features are fictional demo ranges. They are not engineering limits.
SCHEMA: dict[str, dict[str, list[str]]] = {
    "BLAST_FURNACE_UPGRADE": {
        "numeric": ["lining_area_m2", "repair_depth_cm", "zone_count", "shell_repair_area_m2", "taphole_count", "plate_thickness_mm"],
        "categorical": ["scale_band", "work_type", "lining_type"],
    },
    "CONVEYOR_SYSTEM_INSTALLATION": {
        "numeric": ["length_m", "belt_width_mm", "lift_m", "drive_count", "drive_power_kw", "loading_points", "cable_route_m"],
        "categorical": ["work_type", "duty_class", "belt_type"],
    },
    "ELECTRICAL_MAINTENANCE_PROJECT": {
        "numeric": ["motor_count", "panel_count", "switchgear_count", "replacement_fraction", "cable_route_m", "circuit_count", "mean_motor_kw"],
        "categorical": ["work_type", "voltage_class"],
    },
    "COOLING_SYSTEM_UPGRADE": {
        "numeric": ["capacity_kw", "flow_m3h", "head_m", "pipe_route_m", "train_count", "tower_cells", "pipe_diameter_mm"],
        "categorical": ["work_type", "water_condition"],
    },
}

# material code -> display name, base unit. These are fictional template rows.
MATERIALS: dict[str, list[tuple[str, str, str]]] = {
    "BLAST_FURNACE_UPGRADE": [
        ("REF-001", "High-alumina refractory castable", "kg"),
        ("REF-002", "Silicon-carbide/carbon refractory castable", "kg"),
        ("REF-003", "High-alumina refractory brick", "ea"),
        ("REF-004", "Blast furnace taphole clay", "kg"),
        ("REF-005", "Refractory repair grout", "kg"),
        ("REF-006", "Refractory lining anchor", "ea"),
        ("REF-007", "Furnace thermocouple assembly", "ea"),
        ("REF-008", "Furnace shell steel plate", "kg"),
    ],
    "CONVEYOR_SYSTEM_INSTALLATION": [
        ("CON-001", "Conveyor belt section", "m"),
        ("CON-002", "Carrying idler assembly", "ea"),
        ("CON-003", "Return idler assembly", "ea"),
        ("CON-004", "Impact idler assembly", "ea"),
        ("CON-005", "Head/drive pulley assembly", "ea"),
        ("CON-006", "Tail pulley assembly", "ea"),
        ("CON-007", "Conveyor drive gearbox", "ea"),
        ("CON-008", "Conveyor bearing assembly", "ea"),
        ("CON-009", "Primary belt-cleaner blade", "ea"),
        ("CON-010", "Conveyor skirt rubber", "m"),
        ("CON-011", "Belt misalignment switch", "ea"),
        ("ELE-001", "Industrial power cable", "m"),
        ("ELE-002", "Industrial control cable", "m"),
    ],
    "ELECTRICAL_MAINTENANCE_PROJECT": [
        ("ELE-001", "Industrial power cable", "m"),
        ("ELE-002", "Industrial control cable", "m"),
        ("ELE-003", "Low-voltage circuit breaker", "ea"),
        ("ELE-004", "Industrial contactor", "ea"),
        ("ELE-005", "Thermal overload relay", "ea"),
        ("ELE-006", "Variable-frequency drive", "ea"),
        ("ELE-007", "Terminal block", "ea"),
        ("ELE-008", "Cable gland", "ea"),
        ("ELE-009", "Cable lug", "ea"),
        ("ELE-010", "Cable tray section", "m"),
        ("ELE-011", "Industrial junction box", "ea"),
        ("ELE-012", "Industrial fuse", "ea"),
        ("SHR-001", "Industrial electric motor", "ea"),
    ],
    "COOLING_SYSTEM_UPGRADE": [
        ("CLG-001", "Cooling-water circulation pump", "ea"),
        ("CLG-002", "Plate heat exchanger", "ea"),
        ("CLG-003", "Process cooling-water pipe", "m"),
        ("CLG-004", "Cooling-water isolation valve", "ea"),
        ("CLG-005", "Cooling-water check valve", "ea"),
        ("CLG-006", "Cooling-loop Y-strainer", "ea"),
        ("CLG-007", "Cooling-tower fan gearbox", "ea"),
        ("CLG-008", "Cooling-tower fan assembly", "ea"),
        ("CLG-009", "Cooling-tower water-distribution nozzle", "ea"),
        ("CLG-010", "Cooling-water filter element", "ea"),
        ("CLG-011", "Cooling-loop expansion vessel", "ea"),
        ("CLG-012", "Pressure gauge", "ea"),
        ("CLG-013", "Temperature sensor assembly", "ea"),
        ("CLG-014", "Water-treatment chemical", "L"),
    ],
}

PREDICTION_PROJECTS: list[dict[str, Any]] = [
    {
        "project_id": "PRED-BF-01", "category_code": "BLAST_FURNACE_UPGRADE",
        "project_name": "Furnace lining repair",
        "description": "Medium furnace lining patch repair covering 120 m2 to 20 cm depth across four zones, with 12 m2 of shell repair and two tapholes in the outage scope.",
        "features": {"scale_band": "Medium", "work_type": "patch_repair", "lining_type": "high_alumina", "lining_area_m2": 120, "repair_depth_cm": 20, "zone_count": 4, "shell_repair_area_m2": 12, "taphole_count": 2, "plate_thickness_mm": 12},
    },
    {
        "project_id": "PRED-CV-01", "category_code": "CONVEYOR_SYSTEM_INSTALLATION",
        "project_name": "Raw-material conveyor extension",
        "description": "Extend a medium-duty raw-material conveyor by 220 m, using a 1,000 mm belt, 18 m lift, one 250 kW drive and a 300 m electrical cable route.",
        "features": {"work_type": "extension", "duty_class": "medium", "belt_type": "rubber_fabric", "length_m": 220, "belt_width_mm": 1000, "lift_m": 18, "drive_count": 1, "drive_power_kw": 250, "loading_points": 3, "cable_route_m": 300},
    },
    {
        "project_id": "PRED-EL-01", "category_code": "ELECTRICAL_MAINTENANCE_PROJECT",
        "project_name": "Motor and panel maintenance",
        "description": "Maintain 24 assets (12 motors, six panels and six switchgear units) on 400/690 V circuits; replace eight assets, with 300 m of cable route and 18 circuits.",
        "features": {"work_type": "maintenance", "voltage_class": "mixed_400_690", "motor_count": 12, "panel_count": 6, "switchgear_count": 6, "replacement_fraction": 0.333, "cable_route_m": 300, "circuit_count": 18, "mean_motor_kw": 75},
    },
    {
        "project_id": "PRED-CL-01", "category_code": "COOLING_SYSTEM_UPGRADE",
        "project_name": "Process cooling-loop upgrade",
        "description": "Upgrade a two-train process cooling loop rated at 800 kW, 140 m3/h and 28 m head, with 120 m of pipe route and moderate water condition.",
        "features": {"work_type": "upgrade", "water_condition": "moderate", "capacity_kw": 800, "flow_m3h": 140, "head_m": 28, "pipe_route_m": 120, "train_count": 2, "tower_cells": 2, "pipe_diameter_mm": 250},
    },
]


def draw_scope(category: str, rng: random.Random) -> dict[str, Any]:
    if category == "BLAST_FURNACE_UPGRADE":
        band = rng.choice(["Small", "Medium", "Large"])
        band_range = {"Small": (20, 80), "Medium": (70, 160), "Large": (150, 250)}[band]
        return {"scale_band": band, "work_type": rng.choice(["patch_repair", "partial_reline", "major_reline"]),
                "lining_type": rng.choice(["high_alumina", "sic_carbon", "mixed"]),
                "lining_area_m2": rng.randint(*band_range), "repair_depth_cm": rng.randint(5, 40),
                "zone_count": rng.randint(1, 8), "shell_repair_area_m2": rng.randint(0, 30),
                "taphole_count": rng.randint(1, 5), "plate_thickness_mm": rng.choice([8, 10, 12, 16])}
    if category == "CONVEYOR_SYSTEM_INSTALLATION":
        return {"work_type": rng.choice(["new_install", "extension", "drive_retrofit"]),
                "duty_class": rng.choice(["light", "medium", "heavy"]),
                "belt_type": rng.choice(["rubber_fabric", "steel_cord"]),
                "length_m": rng.randint(50, 500), "belt_width_mm": rng.choice([800, 1000, 1200, 1400]),
                "lift_m": rng.randint(0, 50), "drive_count": rng.randint(1, 3),
                "drive_power_kw": rng.choice([75, 110, 160, 250, 400]),
                "loading_points": rng.randint(1, 6), "cable_route_m": rng.randint(50, 700)}
    if category == "ELECTRICAL_MAINTENANCE_PROJECT":
        motors = rng.randint(5, 35)
        panels = rng.randint(2, 15)
        switchgear = rng.randint(1, 15)
        return {"work_type": rng.choice(["preventive_maintenance", "corrective_repair", "replacement"]),
                "voltage_class": rng.choice(["400V", "690V", "mixed_400_690"]),
                "motor_count": motors, "panel_count": panels, "switchgear_count": switchgear,
                "replacement_fraction": round(rng.uniform(0.1, 1.0), 3),
                "cable_route_m": rng.randint(50, 1000), "circuit_count": rng.randint(4, 40),
                "mean_motor_kw": rng.choice([7.5, 15, 30, 55, 75, 110])}
    if category == "COOLING_SYSTEM_UPGRADE":
        return {"work_type": rng.choice(["capacity_upgrade", "equipment_replacement", "loop_repair"]),
                "water_condition": rng.choice(["clean", "moderate", "corrosive"]),
                "capacity_kw": rng.randint(100, 2500), "flow_m3h": rng.randint(25, 600),
                "head_m": rng.randint(10, 60), "pipe_route_m": rng.randint(20, 500),
                "train_count": rng.randint(1, 4), "tower_cells": rng.randint(1, 6),
                "pipe_diameter_mm": rng.choice([80, 100, 150, 200, 250, 300, 400])}
    raise ValueError(f"Unknown category {category}")


def raw_quantities(category: str, f: dict[str, Any]) -> dict[str, float]:
    """Fictional, versioned equations used only to create demo training labels."""
    if category == "BLAST_FURNACE_UPGRADE":
        volume = f["lining_area_m2"] * f["repair_depth_cm"] / 100
        fractions = {"high_alumina": (1.0, 0.0), "sic_carbon": (0.0, 1.0), "mixed": (0.6, 0.4)}[f["lining_type"]]
        return {"REF-001": volume * 1800 * fractions[0], "REF-002": volume * 1800 * fractions[1],
                "REF-003": f["lining_area_m2"] * (0.3 if f["work_type"] == "major_reline" else 0.08),
                "REF-004": f["taphole_count"] * 35, "REF-005": volume * 650,
                "REF-006": f["lining_area_m2"] * 6,
                "REF-007": f["zone_count"],
                "REF-008": f["shell_repair_area_m2"] * f["plate_thickness_mm"] / 1000 * 7850}
    if category == "CONVEYOR_SYSTEM_INSTALLATION":
        length = f["length_m"]
        drives = f["drive_count"]
        loading = f["loading_points"]
        return {"CON-001": length * 1.08, "CON-002": length / 1.2, "CON-003": length / 2.4,
                "CON-004": loading * 4, "CON-005": drives, "CON-006": 1,
                "CON-007": drives, "CON-008": 2 * (drives + 1), "CON-009": drives,
                "CON-010": length * 0.12, "CON-011": max(2, math.ceil(length / 100) * 2),
                "ELE-001": f["cable_route_m"], "ELE-002": f["cable_route_m"] * 1.15}
    if category == "ELECTRICAL_MAINTENANCE_PROJECT":
        replaced_motors = f["motor_count"] * f["replacement_fraction"]
        return {"ELE-001": f["cable_route_m"], "ELE-002": f["cable_route_m"] * 0.8,
                "ELE-003": f["panel_count"] + f["switchgear_count"],
                "ELE-004": replaced_motors, "ELE-005": replaced_motors,
                "ELE-006": max(1, replaced_motors * 0.35), "ELE-007": f["circuit_count"] * 6,
                "ELE-008": f["cable_route_m"] / 8, "ELE-009": replaced_motors * 4,
                "ELE-010": f["cable_route_m"] * 1.05, "ELE-011": f["circuit_count"],
                "ELE-012": f["panel_count"] * 3, "SHR-001": replaced_motors}
    if category == "COOLING_SYSTEM_UPGRADE":
        trains = f["train_count"]
        cells = f["tower_cells"]
        capacity = f["capacity_kw"]
        return {"CLG-001": trains, "CLG-002": trains, "CLG-003": f["pipe_route_m"] * 1.08,
                "CLG-004": trains * 4 + f["pipe_route_m"] / 50, "CLG-005": trains * 2,
                "CLG-006": trains, "CLG-007": cells, "CLG-008": cells,
                "CLG-009": capacity / 8, "CLG-010": trains * 2,
                "CLG-011": capacity / 250, "CLG-012": trains * 2,
                "CLG-013": trains * 3, "CLG-014": capacity * 0.35}
    raise ValueError(f"Unknown category {category}")


def material_lookup(category: str) -> dict[str, tuple[str, str]]:
    return {code: (name, unit) for code, name, unit in MATERIALS[category]}


def eligible_material_codes(category: str, features: dict[str, Any]) -> set[str]:
    """Versioned template guardrails; these choose plausible rows before display."""
    eligible = {code for code, _, _ in MATERIALS[category]}
    if category == "BLAST_FURNACE_UPGRADE":
        if features["lining_type"] == "high_alumina":
            eligible.discard("REF-002")
        elif features["lining_type"] == "sic_carbon":
            eligible.discard("REF-001")
        if features["shell_repair_area_m2"] <= 0:
            eligible.discard("REF-008")
    return eligible


def round_quantity(quantity: float, unit: str, rng: random.Random) -> float:
    varied = max(0.0, quantity * rng.uniform(0.92, 1.08))
    if unit == "ea":
        return float(max(0, round(varied)))
    return round(varied, 2)


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "data")
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    rng = random.Random(SEED)
    project_rows: list[dict[str, Any]] = []
    requirement_rows: list[dict[str, Any]] = []
    split_by_id: dict[str, str] = {}
    feature_columns_by_category: dict[str, list[str]] = {}
    category_project_rows: dict[str, list[dict[str, Any]]] = {}

    for category in SCHEMA:
        numeric = SCHEMA[category]["numeric"]
        categorical = SCHEMA[category]["categorical"]
        feature_columns = numeric + categorical
        feature_columns_by_category[category] = feature_columns
        rows: list[dict[str, Any]] = []
        for index in range(1, PROJECTS_PER_CATEGORY + 1):
            project_id = f"SYN-{category[:3]}-{index:03d}"
            features = draw_scope(category, rng)
            rows.append({"project_id": project_id, "category_code": category, **features})
        shuffled = rows[:]
        rng.shuffle(shuffled)
        validation_ids = {r["project_id"] for r in shuffled[:PROJECTS_PER_CATEGORY // 5]}
        for row in rows:
            split = "validation" if row["project_id"] in validation_ids else "train"
            split_by_id[row["project_id"]] = split
            enriched = {**row, "split": split, "data_origin": "synthetic", "generator_version": GENERATOR_VERSION}
            project_rows.append(enriched)
            category_project_rows.setdefault(category, []).append(enriched)

            raw = raw_quantities(category, row)
            lookup = material_lookup(category)
            for code, value in raw.items():
                name, unit = lookup[code]
                quantity = round_quantity(value, unit, rng)
                requirement_rows.append({"project_id": row["project_id"], "category_code": category,
                                         "material_code": code, "material_name": name, "unit": unit,
                                         "synthetic_reference_requirement_quantity": quantity,
                                         "required": quantity > 0,
                                         "data_origin": "synthetic", "generator_version": GENERATOR_VERSION,
                                         "equation_version": GENERATOR_VERSION})

    prediction_feature_rows: list[dict[str, Any]] = []
    prediction_requirements: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {"generator_version": GENERATOR_VERSION, "model_version": MODEL_VERSION,
                               "seed": SEED, "projects_per_category": PROJECTS_PER_CATEGORY,
                               "synthetic_only_notice": "Scores measure reproduction of fictional generator equations, not real-world accuracy.",
                               "categories": {}}
    fitted_models: dict[str, Any] = {}

    for scenario in PREDICTION_PROJECTS:
        category = scenario["category_code"]
        prediction_feature_rows.append({"project_id": scenario["project_id"], "project_name": scenario["project_name"],
                                        "category_code": category, "description": scenario["description"],
                                        "data_origin": "synthetic_prediction_example", **scenario["features"]})

    for category, rows in category_project_rows.items():
        schema = SCHEMA[category]
        numeric = schema["numeric"]
        categorical = schema["categorical"]
        feature_columns = feature_columns_by_category[category]
        materials = MATERIALS[category]
        material_codes = [m[0] for m in materials]
        project_ids = [r["project_id"] for r in rows]
        train_ids = {pid for pid in project_ids if split_by_id[pid] == "train"}
        val_ids = {pid for pid in project_ids if split_by_id[pid] == "validation"}
        category_requirements = [r for r in requirement_rows if r["category_code"] == category]
        label_map = {(r["project_id"], r["material_code"]): r["synthetic_reference_requirement_quantity"] for r in category_requirements}

        x_train = pd.DataFrame([{k: r[k] for k in feature_columns} for r in rows if r["project_id"] in train_ids])
        x_val = pd.DataFrame([{k: r[k] for k in feature_columns} for r in rows if r["project_id"] in val_ids])
        y_train = np.array([[label_map[(r["project_id"], code)] for code in material_codes]
                            for r in rows if r["project_id"] in train_ids], dtype=float)
        y_val = np.array([[label_map[(r["project_id"], code)] for code in material_codes]
                          for r in rows if r["project_id"] in val_ids], dtype=float)

        preprocessor = ColumnTransformer([
            ("categorical", OneHotEncoder(handle_unknown="ignore"), categorical),
            ("numeric", "passthrough", numeric),
        ])
        model = Pipeline([
            ("features", preprocessor),
            ("regressor", RandomForestRegressor(n_estimators=160, min_samples_leaf=2,
                                                max_features=1.0, random_state=SEED, n_jobs=-1)),
        ])
        model.fit(x_train, y_train)
        prediction = model.predict(x_val)
        baseline_values = []
        for column in range(y_train.shape[1]):
            positive = y_train[:, column][y_train[:, column] > 0]
            baseline_values.append(float(np.median(positive)) if len(positive) else 0.0)
        baseline = np.tile(np.array(baseline_values), (len(y_val), 1))
        material_metrics = {}
        for index, code in enumerate(material_codes):
            # The template only presents a material when its synthetic scope rules apply.
            mask = y_val[:, index] > 0
            actual = y_val[:, index][mask]
            estimate = prediction[:, index][mask]
            base = baseline[:, index][mask]
            denom = float(np.abs(actual).sum())
            material_metrics[code] = {
                "validation_mae": round(float(mean_absolute_error(actual, estimate)), 3) if len(actual) else None,
                "median_baseline_mae": round(float(mean_absolute_error(actual, base)), 3) if len(actual) else None,
                "validation_wape_pct": round(float(np.abs(actual - estimate).sum() / denom * 100), 2) if denom else None,
                "validation_projects_with_material": len(actual),
            }
        metrics["categories"][category] = {"train_projects": len(train_ids), "validation_projects": len(val_ids),
                                           "feature_columns": feature_columns, "materials": material_metrics}
        fitted_models[category] = {"pipeline": model, "feature_columns": feature_columns,
                                   "material_codes": material_codes}

        estimators = model.named_steps["regressor"].estimators_
        for scenario in [p for p in PREDICTION_PROJECTS if p["category_code"] == category]:
            x_pred = pd.DataFrame([{k: scenario["features"][k] for k in feature_columns}])
            tree_predictions = np.stack([tree.predict(model.named_steps["features"].transform(x_pred))[0]
                                         for tree in estimators], axis=0)
            means = model.predict(x_pred)[0]
            low = np.percentile(tree_predictions, 10, axis=0)
            high = np.percentile(tree_predictions, 90, axis=0)
            lookup = material_lookup(category)
            for index, code in enumerate(material_codes):
                if code not in eligible_material_codes(category, scenario["features"]):
                    continue
                name, unit = lookup[code]
                predicted = max(0.0, float(means[index]))
                if unit == "ea":
                    predicted = float(max(0, round(predicted)))
                prediction_requirements.append({"project_id": scenario["project_id"], "project_name": scenario["project_name"],
                    "category_code": category, "material_code": code, "material_name": name, "unit": unit,
                    "predicted_quantity": round(predicted, 2), "tree_p10": round(max(0.0, float(low[index])), 2),
                    "tree_p90": round(max(0.0, float(high[index])), 2), "model_version": MODEL_VERSION,
                    "data_origin": "synthetic_model_prediction", "synthetic_notice": "Demo estimate only; not an approved material take-off."})

    write_csv(out / "training_projects.csv", project_rows,
              ["project_id", "category_code", "split", "data_origin", "generator_version"] +
              list(dict.fromkeys(k for row in project_rows for k in row if k not in {"project_id", "category_code", "split", "data_origin", "generator_version"})))
    write_csv(out / "training_requirements.csv", requirement_rows,
              ["project_id", "category_code", "material_code", "material_name", "unit",
               "synthetic_reference_requirement_quantity", "required", "data_origin", "generator_version", "equation_version"])
    write_csv(out / "prediction_projects.csv", prediction_feature_rows,
              ["project_id", "project_name", "category_code", "description", "data_origin"] +
              list(dict.fromkeys(k for row in prediction_feature_rows for k in row if k not in {"project_id", "project_name", "category_code", "description", "data_origin"})))
    write_csv(out / "predicted_material_drafts.csv", prediction_requirements,
              ["project_id", "project_name", "category_code", "material_code", "material_name", "unit",
               "predicted_quantity", "tree_p10", "tree_p90", "model_version", "data_origin", "synthetic_notice"])
    metrics["library_versions"] = {"scikit_learn": sklearn.__version__, "numpy": np.__version__, "pandas": pd.__version__}
    (out / "evaluation_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    joblib.dump({"models": fitted_models, "generator_version": GENERATOR_VERSION,
                 "model_version": MODEL_VERSION, "seed": SEED}, out / "synthetic_material_models.joblib")
    print(f"Generated {len(project_rows)} synthetic training projects and {len(prediction_feature_rows)} held-out prediction projects.")
    print(f"Wrote dataset, evaluation metrics, predictions, and model bundle to {out.resolve()}")


if __name__ == "__main__":
    main()
