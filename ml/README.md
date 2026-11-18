# Quantity-estimate model (synthetic data)

Learns material quantities from the 40 COMPLETED synthetic projects and evaluates them with
project-level splits. Output is a fictional estimate, not an engineering recommendation or BOM.

## Run (from the `ml` folder, after generating the CSVs)

    python -m pip install pandas numpy scikit-learn
    python train_quantity_model.py                      # reads ../data/generated/v1/*.csv
    python train_quantity_model.py --source db          # reads PostgreSQL via ../backend/.env (needs psycopg2-binary, python-dotenv)
    python train_quantity_model.py --demo-category CONVEYOR_SYSTEM_INSTALLATION --demo-scale 1500
    python train_quantity_model.py --demo-category BLAST_FURNACE_UPGRADE --demo-level Large

Outputs (in `artifacts/`): `quantity_model_v1.json` (plain-JSON coefficients, usable by the API
without scikit-learn), `quantity_model_metrics.json`, `quantity_model_report.md`.

## Rules the evaluation follows
- Split by PROJECT, never by line: 5-fold CV stratified by category (20 repeats) plus a holdout of
  the latest 2 projects per category.
- Features: category, material, scale. Target: `approved_quantity`.
- NOT used as features: predicted/proposed quantity, allocations, consumption, receipts, stock.
- `rule_baseline` (stored predicted_quantity) is a comparison only. It is the generator's noise-free
  centre, so it approximates the noise floor and is not expected to be beaten.
- Active projects are never used for training or testing.

## Caveats
Synthetic data from known rules, only 40 projects. Scores show the pipeline recovers the pattern;
they say nothing about real-world accuracy. Predictions outside the training scale range are flagged
`extrapolated_scale`. Use `predict_estimate()` in the script to serve estimates from the JSON model.
