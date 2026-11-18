# Quantity-estimate model report (v1.0.0)

> SYNTHETIC DATA. Fictional prototype; estimates are not engineering recommendations or an approved bill of materials.

**Data:** 40 completed projects ({'BLAST_FURNACE_UPGRADE': 10, 'CONVEYOR_SYSTEM_INSTALLATION': 10, 'COOLING_SYSTEM_UPGRADE': 10, 'ELECTRICAL_MAINTENANCE_PROJECT': 10}). Active projects are excluded.
**Target:** `approved_quantity` per requirement line. **Features:** category, material, scale only.

## Protocol
- 5-fold project-level CV, stratified by category, 20 repeats. A project's lines never appear in both train and test.
- Time holdout: latest 2 projects per category by start_date (8 projects).
- APE = |estimate - approved| / approved. Value-weighted APE weights lines by preferred-supplier unit price.

## Cross-validation (mean over repeats)
| Model | Median APE | Mean APE | Within 10% | Within 20% | Value-weighted APE |
|---|---|---|---|---|---|
| naive_median | 33.8% (+/-0.8%) | 61.3% | 21.6% | 32.2% | 54.5% |
| rule_baseline | 1.2% (+/-0.0%) | 6.4% | 73.1% | 91.7% | 9.7% |
| scale_model | 7.1% (+/-0.3%) | 10.6% | 59.9% | 85.1% | 13.4% |
| gbm | 21.9% (+/-1.0%) | 26.3% | 29.2% | 47.6% | 19.8% |

## Time-ordered holdout
| Model | Median APE | Mean APE | Within 10% | Within 20% | Value-weighted APE |
|---|---|---|---|---|---|
| naive_median | 42.9% | 55.0% | 12.0% | 18.7% | 40.4% |
| rule_baseline | 0.0% | 6.1% | 72.0% | 93.3% | 12.9% |
| scale_model | 7.8% | 10.8% | 58.0% | 84.7% | 17.7% |
| gbm | 24.4% | 30.3% | 30.0% | 45.3% | 25.5% |

## How to read this
- `rule_baseline` is the stored synthetic rule value. It is the noise-free centre the data was generated
  around, **not a learned model**, so its error approximates the irreducible noise: 6.4% mean APE and
  9.7% value-weighted APE. Its *median* APE (1.2%) is near zero only because many small whole-number
  lines (for example 1 or 2 pulleys) round to exactly the same count, so prefer mean and value-weighted APE
  when comparing. No model trained on this data should be expected to beat the baseline.
- Among learned models, **scale_model** has the lowest cross-validated median APE (7.1%).
  `naive_median` ignores scale and shows how much the scale information is worth.
- The final saved model is the `scale_model` fitted on all completed projects, with empirical p10/p90
  ranges from out-of-fold actual/estimate ratios.

## Limitations (important)
- Synthetic data generated from known rules: good scores show the pipeline can recover the pattern,
  **not** that it would work on real projects.
- Only 40 projects (10 per category at minimum). Differences of a few percentage points are within noise.
- Small integer quantities (for example 1 vs 2 pulleys) inflate APE regardless of model quality.
- Estimates outside the training scale range are flagged `extrapolated_scale` and should not be trusted.
