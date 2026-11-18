# SupplyChain AI — Fictional Starter Material Catalogue

**Purpose:** Seed data for the fictional prototype only. This is not an approved bill of materials, purchasing list, or engineering recommendation. Actual requirements depend on equipment design and qualified engineering review.

**Unit convention:** Each material has one base unit. Use `ea` for discrete items, kilograms for bulk solids, metres for linear goods, and litres for liquid treatment products. Do not convert units in the first version.

## Draft material master

| Material code | Fictional material name | Material category | Base unit | Candidate project categories |
|---|---|---|---|---|
| REF-001 | High-alumina refractory castable | Refractory | kg | Blast Furnace Upgrade |
| REF-002 | Silicon-carbide/carbon refractory castable | Refractory | kg | Blast Furnace Upgrade |
| REF-003 | High-alumina refractory brick | Refractory | ea | Blast Furnace Upgrade |
| REF-004 | Blast furnace taphole clay | Refractory | kg | Blast Furnace Upgrade |
| REF-005 | Refractory repair grout | Refractory | kg | Blast Furnace Upgrade |
| REF-006 | Refractory lining anchor | Mechanical spare | ea | Blast Furnace Upgrade |
| REF-007 | Furnace thermocouple assembly | Instrumentation | ea | Blast Furnace Upgrade |
| REF-008 | Furnace shell steel plate | Structural material | kg | Blast Furnace Upgrade |
| CON-001 | Conveyor belt section | Conveyor spare | m | Conveyor System Installation |
| CON-002 | Carrying idler assembly | Conveyor spare | ea | Conveyor System Installation |
| CON-003 | Return idler assembly | Conveyor spare | ea | Conveyor System Installation |
| CON-004 | Impact idler assembly | Conveyor spare | ea | Conveyor System Installation |
| CON-005 | Head/drive pulley assembly | Conveyor spare | ea | Conveyor System Installation |
| CON-006 | Tail pulley assembly | Conveyor spare | ea | Conveyor System Installation |
| CON-007 | Conveyor drive gearbox | Mechanical spare | ea | Conveyor System Installation |
| CON-008 | Conveyor bearing assembly | Mechanical spare | ea | Conveyor System Installation |
| CON-009 | Primary belt-cleaner blade | Conveyor spare | ea | Conveyor System Installation |
| CON-010 | Conveyor skirt rubber | Conveyor spare | m | Conveyor System Installation |
| CON-011 | Belt misalignment switch | Electrical component | ea | Conveyor System Installation |
| ELE-001 | Industrial power cable | Electrical component | m | Conveyor System Installation; Electrical Maintenance Project; Cooling System Upgrade |
| ELE-002 | Industrial control cable | Electrical component | m | Conveyor System Installation; Electrical Maintenance Project; Cooling System Upgrade |
| ELE-003 | Low-voltage circuit breaker | Electrical component | ea | Electrical Maintenance Project; Conveyor System Installation; Cooling System Upgrade |
| ELE-004 | Industrial contactor | Electrical component | ea | Electrical Maintenance Project; Conveyor System Installation; Cooling System Upgrade |
| ELE-005 | Thermal overload relay | Electrical component | ea | Electrical Maintenance Project; Conveyor System Installation; Cooling System Upgrade |
| ELE-006 | Variable-frequency drive | Electrical component | ea | Electrical Maintenance Project; Conveyor System Installation; Cooling System Upgrade |
| ELE-007 | Terminal block | Electrical component | ea | Electrical Maintenance Project; Conveyor System Installation; Cooling System Upgrade |
| ELE-008 | Cable gland | Electrical component | ea | Electrical Maintenance Project; Conveyor System Installation; Cooling System Upgrade |
| ELE-009 | Cable lug | Electrical component | ea | Electrical Maintenance Project; Conveyor System Installation; Cooling System Upgrade |
| ELE-010 | Cable tray section | Electrical component | m | Electrical Maintenance Project; Conveyor System Installation; Cooling System Upgrade |
| ELE-011 | Industrial junction box | Electrical component | ea | Electrical Maintenance Project; Conveyor System Installation; Cooling System Upgrade |
| ELE-012 | Industrial fuse | Electrical component | ea | Electrical Maintenance Project; Conveyor System Installation; Cooling System Upgrade |
| SHR-001 | Industrial electric motor | Mechanical/electrical spare | ea | Conveyor System Installation; Electrical Maintenance Project; Cooling System Upgrade |
| CLG-001 | Cooling-water circulation pump | Mechanical spare | ea | Cooling System Upgrade |
| CLG-002 | Plate heat exchanger | Cooling equipment | ea | Cooling System Upgrade |
| CLG-003 | Process cooling-water pipe | Piping | m | Cooling System Upgrade |
| CLG-004 | Cooling-water isolation valve | Piping | ea | Cooling System Upgrade |
| CLG-005 | Cooling-water check valve | Piping | ea | Cooling System Upgrade |
| CLG-006 | Cooling-loop Y-strainer | Piping | ea | Cooling System Upgrade |
| CLG-007 | Cooling-tower fan gearbox | Mechanical spare | ea | Cooling System Upgrade |
| CLG-008 | Cooling-tower fan assembly | Mechanical spare | ea | Cooling System Upgrade |
| CLG-009 | Cooling-tower water-distribution nozzle | Cooling equipment | ea | Cooling System Upgrade |
| CLG-010 | Cooling-water filter element | Consumable | ea | Cooling System Upgrade |
| CLG-011 | Cooling-loop expansion vessel | Cooling equipment | ea | Cooling System Upgrade |
| CLG-012 | Pressure gauge | Instrumentation | ea | Cooling System Upgrade; Electrical Maintenance Project |
| CLG-013 | Temperature sensor assembly | Instrumentation | ea | Cooling System Upgrade; Blast Furnace Upgrade; Electrical Maintenance Project |
| CLG-014 | Water-treatment chemical | Chemical | L | Cooling System Upgrade |

## How to use this catalogue in the database

The rows above seed the material master; they do not say which materials a project actually requires or in what quantities. A material can be shared by multiple project categories, so do not add a project-category field directly to the materials table.

Add a junction/rules table called project_category_material_rules:

| Column | Type | Purpose |
|---|---|---|
| rule_id | BIGINT identity primary key | Rule identifier |
| project_category_id | BIGINT | FK to project_categories |
| material_id | BIGINT | FK to materials |
| scale_band | VARCHAR(10) | all, small, medium, or large; use bands for the ordinal furnace scale |
| base_quantity | NUMERIC(14,3) | Synthetic baseline quantity in the material's base unit |
| quantity_per_scale_unit | NUMERIC(14,6) | Synthetic rate for numeric scale categories; zero or null for ordinal bands |
| rule_version | VARCHAR(30) | Version of the fictional rule set |
| is_active | BOOLEAN | Allows a rule to be retired without deleting history |

Use one rule row per category/material/scale band. For conveyor length, equipment count, and cooling capacity, a draft quantity can be calculated from a fictional base quantity plus scale multiplied by quantity_per_scale_unit. For furnace upgrades, choose the rule matching Small, Medium, or Large. These coefficients are synthetic assumptions; label them as such.

The generator can then create a draft estimate from the selected category and scale. Keep the original predicted quantity, project-head-edited quantity, and approved quantity in the project requirement tables.

## Technical plausibility references

These references were used only to check component naming. They do not provide the prototype's fictional quantities:

- Vesuvius describes blast-furnace stack repair products including high-alumina and silicon-carbide/carbon castables, grout, and taphole clay: https://www.vesuvius.com/en/our-solutions/en-uk/iron-and-steel/iron-making/stack-solutions.html
- Metso describes conveyor belts, idlers/rollers, pulleys, motors, gearboxes, cleaners, and related components: https://www.metso.com/products-and-services/parts/conveyor-parts/
- ABB lists industrial low-voltage motor-control components such as circuit breakers, contactors, overload relays, drives, and motor-control centers: https://new.abb.com/low-voltage/products/switchgear/mcc
- SPX/Marley lists cooling-tower fans, gearboxes, motors, fill, nozzles, valves, and drift eliminators: https://spxcooling.com/cooling-tower-parts/
- Carrier's installation schematic identifies cooling-loop elements such as pumps, piping, valves, filters, heat exchangers, and gauges: https://brandportal.carrier.com/m/4e376b409d09d9a9/original/EN7546022-03_IOM_05_2025_30WI.pdf

