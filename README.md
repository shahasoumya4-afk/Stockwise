# Synthetic dataset generator (fictional inventory-management prototype)

> **SYNTHETIC DATA.** Every record, quantity, price, rule and date is a fictional assumption.
> Nothing here is an approved bill of materials, an engineering recommendation, or derived
> from any real company's data. No real employees, suppliers or confidential data are used.

## Install and run

```bash
python -m venv .venv && source .venv/bin/activate
pip install pandas numpy
python generate_dataset.py --config config.sample.json
```

Options: `--catalogue PATH` (material catalogue markdown), `--output-dir PATH`,
`--dump-default-config PATH` (writes every default, including the quantity rules).
No network access is used. Output goes to `data/generated/v1/`. The same seed, config and
catalogue produce byte-identical files (SHA-256 per file is in the manifest).

The catalogue path defaults to `SupplyChain_AI_Project_Overview.md` (the file name as
uploaded). Change `catalogue_path` if your copy is named differently.

## Stress scenario (optional, for demos)

    python generate_dataset.py --config config.sample.json --stress --output-dir data/generated/v1_stress
    python load_data.py --dbname inventory_db --user postgres --data-dir data/generated/v1_stress --reset

Thinner stock (no overbuying, no cover stock, slower replenishment reviews, delayed recent supplier
deliveries) and most future-needed lines of active projects only partly allocated, with open orders
that are on time, late, partial, or missing. Settings are in the `stress` block of the config
(`enabled` is false by default). Completed-project requirements are identical to the baseline, so the
quantity model is unaffected. To go back: rerun the baseline command and load with `--data-dir data/generated/v1 --reset`.
With the default seed the shortage-risk endpoints show 88 OK, 10 WATCH, 2 AT_RISK and 2 SHORT lines.

## Generated files (all under `data/generated/v1/`)

`departments, roles, users, project_categories, material_categories, units_of_measure,
materials, warehouses, suppliers, material_suppliers, project_category_material_rules,
projects, project_requirement_versions, project_material_requirements, inventory,
inventory_allocations, purchase_orders, purchase_order_lines, inventory_transactions`
(each as `<name>.csv`), plus `generation_manifest.json` (seed, generator version,
configuration, row counts, column types, file hashes, validation summary, synthetic label).

Default row counts: 5 departments, 5 roles, 20 users, 4 project categories, 11 material
categories, 4 units, 46 materials, 3 warehouses, 8 suppliers, 45 projects (40 Completed +
5 Active), 138 inventory rows (46 materials x 3 warehouses).

## Import order (parents first)

1. departments  2. roles  3. users  4. project_categories  5. material_categories
6. units_of_measure  7. materials  8. warehouses  9. suppliers  10. material_suppliers
11. project_category_material_rules  12. projects  13. project_requirement_versions
14. project_material_requirements  15. inventory  16. inventory_allocations
17. purchase_orders  18. purchase_order_lines  19. inventory_transactions

CSV conventions: UTF-8, header row, ISO dates, ISO-8601 UTC timestamps, `true`/`false`
booleans, empty unquoted field = NULL (PostgreSQL `COPY ... CSV` default). Column types are
listed per table in the manifest.

## Generation logic in brief

* **Materials** come only from the catalogue (codes, names, categories, units, candidate
  categories are validated, never renamed). Unit conversion is not performed.
* **Rules** (`project_category_material_rules`): furnace upgrades use fixed quantities per
  `small/medium/large`; the other three categories use `base + quantity_per_scale_unit x scale`
  with band `all`. A rule set must cover exactly the catalogue's candidate materials for that
  category; the generator stops if it does not.
* **Requirements**: for each project, `predicted_quantity` is the deterministic rule value.
  `proposed_quantity` applies a project-level factor and line noise to most lines
  (project-head edit). `approved_quantity` adds occasional reviewer adjustments. All three are
  stored separately. `confidence_score` is NULL on purpose (no forecast is fabricated).
* **Lifecycle**: one `Approved` requirement version per project; Completed projects ended
  before the as-of date; Active projects straddle it. Draft is a supported state in the schema
  but none are generated.
* **Operations** are simulated on a per (warehouse, material) ledger: allocations are checked
  against available stock (on-hand minus reservations); shortfalls trigger back-dated
  purchase orders (Monday order dates, supplier lead times, occasional late and partial
  receipts) or, for demand too early to order, a larger opening balance. Completed projects
  consume 92-100% of allocation and release the rest. Active projects have partial consumption,
  some lines only partly allocated, and a few open (Ordered / Partially Received) purchase orders.
  Routine min/max replenishment (v1.1.0): every `review_interval_days` (weekly, Mondays) each
  warehouse/material position (available + on order) at or below its reorder point is topped up to
  reorder point + `replenishment_cover_days` of demand. Reorder point = safety stock + demand over the
  preferred supplier's lead time, from that warehouse's own consumption history (synthetic policy).
  Receipts only add stock, so this cannot break any integrity guarantee. Set
  `inventory.replenishment_enabled` to false to get the old just-in-time behaviour.
* **Inventory**: `on_hand_quantity` equals the opening-balance transaction plus all later
  deltas. Allocations reduce *available* stock only. Remaining allocation is derived:
  `allocated_quantity - sum(consumption transactions for that allocation_id)`, and zero once
  status is `Released`.
* **Validation** (114 checks, run before any file is written): PK/FK integrity, unique codes,
  catalogue fidelity, candidate-material rules, status/date logic, no negative stock at any
  point in time, allocations never exceeding available stock or approved quantity, no
  over-receipts, receipts linked to the right PO line, inventory reconciliation.

## Assumptions to confirm (not given in the catalogue or brief)

1. `projects.scale_level` holds the furnace band only; `scale_value` holds length / count / kW
   (NULL for furnace); `equipment_count` is filled only for Electrical Maintenance (equal to
   `scale_value`), otherwise NULL.
2. Roles are placeholders (ADMIN, PROJECT_HEAD, INVENTORY_MANAGER, PROCUREMENT_OFFICER,
   VIEWER). No generated user holds ADMIN. Users are named `Demo Employee NNN`, are `Disabled`,
   have `password_hash = '!DISABLED-NO-LOGIN'` and `@example.invalid` emails.
3. Status vocabularies: project `Active/Completed`; review `Approved`; allocation
   `Active/Consumed/Released`; PO `Ordered/Partially Received/Received`; transaction type
   `Opening Balance/Receipt/Consumption`.
4. Reviewers, allocators and stock clerks are generated INVENTORY_MANAGER users; requirement
   generation and opening balances use NULL (system) actors.
5. Currency is INR (configurable); prices, lead times, MOQs and all quantities are fictional.
6. "Dashboard data contains only the 5 active projects" is interpreted as a query filter
   (`projects.status = 'Active'`), not a separate file.

## Synthetic-data limitations and leakage guidance

* 40 historical projects are for initial experiments only; results are not evidence of
  reliable or generalizable ML performance. Increase `completed_projects_per_category` later.
* Targets are generated from the same rule table the generator uses, so a model can learn the
  rules almost exactly. Treat any accuracy as a pipeline check, not evidence of real skill.
* `predicted_quantity` is a rule baseline derived from the same features. Do not use it as a
  model feature for predicting `approved_quantity`; use it only as a baseline to beat.
* Split train/test **by project** (grouped or time-based on `start_date`), never by line.
  Lines of one project share a latent project factor.
* Use only information available at estimate time as features: category, scale, department,
  dates. Consumption, allocations and receipts are post-approval outcomes.
* Opening balances, safety stock, reorder points and replenishment orders are computed from the generated demand, so
  they must not be used as features for forecasting that same demand.
* Forecast outputs, risk alerts, anomaly outputs and procurement recommendations are NOT
  generated; the application backend must compute them from this operational data.
