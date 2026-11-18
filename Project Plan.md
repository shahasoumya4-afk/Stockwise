We’ve finished three phases and are partway through the fourth. The plan below combines your two documents with what we’ve actually built. I’ve adjusted the order in two places, which I flag at the end.

Where we are
Phase	What	Status
1	Synthetic data, schema, database load	Done
2	Read-only backend API	Done
3	Quantity-estimate model (experiment)	Done, not yet connected to the API
4	Shortage risk and procurement recommendations	In progress (you are here)
5	Roles and schema alignment	Not started
6	Accounts and authentication	Not started
7	Frontend	Not started
8	Write operations and audit history	Not started
9	End-to-end verification	Not started
10	Packaging and demo	Not started
Phase details

Phase 1: Data foundation (done)

The generator creates 46 materials, 40 completed and 5 active projects, and stock with weekly replenishment. It passes 114 integrity checks and is deterministic.
schema.sql and load_data.py create and load the database, and verify it against the manifest.
You’ve already regenerated and reloaded the data (v1.1.0).

Phase 2: Read-only API (done)

Projects, requirements, dashboard summary, materials, rules, inventory with reserved and available stock, transactions and purchase orders are all served. Connections are read-only.

Phase 3: Quantity-estimate model (done as an experiment)

It uses project-level splits, and the saved per-material scale model has about 10.6% mean error against a 6.4% noise floor.
It is only evaluated, not yet usable by the app, and it uses category, material and scale only. Your plan also listed department and dates as candidate features. In this synthetic data they carry no signal by construction, since they’re random with respect to quantities. I’d document that rather than add them.

Phase 4: Shortage risk and procurement recommendations (in progress)

Done: the explainable risk logic (OK, WATCH, AT_RISK, SHORT) with urgency, plus /api/risk/shortages, /summary and /reorder. It passed 10 scenario tests.
Right now: copy risk.py, common.py and the new main.py into backend\app\, restart, and confirm /api/risk/summary shows 101 OK, 1 WATCH.
Still to do:
A stress scenario in the generator, because the current data is healthy and shows almost no risk.
A recommendation layer that shows what to order, how much (respecting minimum order quantities), by when (using lead time), and from which supplier, display-only.
Suggested warehouse sources for allocations, for the project head to confirm.
An estimate-preview endpoint backed by the Phase 3 model.
Done when: a stress dataset produces sensible SHORT and AT_RISK cases with recommendations that can be checked by hand.

Phase 5: Roles and schema alignment

Replace the placeholder roles with system admin, project head and IT employee. Generated users and actors need re-mapping, because inventory managers and procurement officers no longer exist.
Add the missing tables: an audit log, and whatever authentication needs (sessions or tokens). Use the existing requested-role and assigned-role columns for signup.
Regenerate, reload and re-verify.
Done when: the schema supports every permission and workflow in your plan.

Phase 6: Accounts and authentication

Signup (name, email, password, employee ID, department, requested role), pending approval, and role assignment by the system admin.
Department management, a secure way to create the first admin, and enforcement that a requested role grants nothing until approved.
Done when: the three roles can log in, and the API rejects access that a role shouldn’t have.

Phase 7: Frontend

Choose a stack (see below), then build the project dashboard, project details, material estimates, inventory availability and shortage recommendations.
Screens must follow permissions: IT employees see no inventory, and drafts are private.

Phase 8: Write operations and audit

Project submission, estimate edits and approval (Draft to Active), allocation, consumption, receipts and count corrections.
Every inventory change is a transaction with an audit record. No automatic purchase orders.

Phase 9: End-to-end verification

Check each role against what it may see and change, and check that approvals feed inventory calculations at the right time.
Check that stock stays consistent through allocation, receipt and consumption.

Phase 10: Packaging

Setup, configuration, loading, running the API and frontend, sample accounts, and the synthetic-data limitations.
Immediate next steps
Finish the Phase 4 file placement and check the risk endpoints.
Build the stress scenario and recommendation layer.
Decide the role mapping.
Differences from your documents
Model before risk logic: your list put model evaluation after risk logic. I did it first, which was harmless because they’re independent.
Roles and authentication before the frontend: I’d move role alignment and authentication ahead of the frontend, so screens are built with real permissions rather than reworked later. Your list had the frontend earlier, and I’m happy to swap back if you want to see screens sooner.
Decisions I need from you eventually
The role mapping, ideally before Phase 5.
The frontend stack. React with Vite is the usual pairing with FastAPI, and a simpler alternative would be quicker for a prototype. You can decide at Phase 7.
Shortage-risk thresholds, such as the safety buffer in days. I’ve defaulted it to 0 and it can be adjusted.
Hosting, which we can leave until packaging.