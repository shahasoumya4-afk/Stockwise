"""Read-only inventory assistant using a lightweight TF-IDF intent classifier."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from . import db
from .common import OPEN_PO_STATUSES, STOCK_CTE, SYNTHETIC_NOTICE, resolve_as_of
from .risk import compute_risk

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

# Curated labeled utterances are the intent training corpus. Entity values are resolved from DB.
EXAMPLES = {
    "active_projects": [
        "Which projects are ongoing?", "show active projects", "list current projects",
        "what work is underway", "projects currently in progress", "which projects are not completed",
    ],
    "project_remaining": [
        "How much stock is left for project 12?", "remaining material for project id",
        "how much allocated material remains in a project", "what is left in project allocation",
        "show project inventory balance",
    ],
    "project_requirements": [
        "what materials does project 12 need", "show project material requirements",
        "list approved materials and quantities for this project", "what is required for project id",
    ],
    "project_status": [
        "what is the status of project 12", "show project details and dates",
        "when does this project finish", "who is leading this project",
    ],
    "material_stock": [
        "how much ELE-001 stock is available", "show on hand quantity and reserved stock",
        "how much cable do we have", "which warehouse has this material", "check stock levels for a material",
    ],
    "shortages": [
        "which projects have material shortages", "show urgent shortage risks",
        "what materials are short for project 12", "which shortage is most urgent",
        "show uncovered requirements", "what demand is not covered by stock or orders",
    ],
    "purchase_orders": [
        "when will the supplier order arrive", "show open purchase orders for this material",
        "what is the delivery date for ELE-001", "which supplier is sending this item",
        "can the purchase order arrive before the need date",
    ],
    "reorder": [
        "which materials need restocking", "what is below the reorder point",
        "what should we order soon", "show low stock items and incoming orders",
    ],
    "access": [
        "who has access to this project inventory", "who can view the stock data",
        "which users can see project materials", "who is allowed to access inventory",
        "what roles can view this project",
    ],
}
STOP = set("a an the is are was were do does did can could would should will we i me my our you your for of to in on at by with and or please tell show give get much many there be it this that now currently".split())
SYNONYMS = {
    "ongoing": "active", "underway": "active", "running": "active", "current": "active",
    "progress": "active", "left": "remaining", "remain": "remaining", "unused": "remaining",
    "inventory": "stock", "inventories": "stock", "available": "stock", "onhand": "stock",
    "materials": "material", "items": "material", "shortages": "shortage", "short": "shortage",
    "uncovered": "shortage", "risks": "shortage", "risk": "shortage", "restock": "reorder",
    "restocking": "reorder", "replenishment": "reorder", "replenish": "reorder",
    "orders": "order", "purchase": "order", "purchases": "order", "supplier": "order",
    "delivery": "arrival", "arrive": "arrival", "arrives": "arrival", "eta": "arrival",
    "permission": "access", "permissions": "access", "view": "access", "see": "access",
    "allowed": "access", "users": "user", "roles": "role", "finishes": "finish", "ends": "finish",
}


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.casefold().replace("on-hand", "onhand"))
    return [SYNONYMS.get(w, w) for w in words if w not in STOP and len(w) > 1]


_CORPUS = [(intent, phrase) for intent, phrases in EXAMPLES.items() for phrase in phrases]
_DF: Counter[str] = Counter()
for _, phrase in _CORPUS:
    _DF.update(set(_tokens(phrase)))
_IDF = {term: math.log((len(_CORPUS) + 1) / (count + 1)) + 1 for term, count in _DF.items()}


def _vector(text: str) -> dict[str, float]:
    counts = Counter(_tokens(text))
    return {term: (1 + math.log(count)) * _IDF.get(term, 1.0) for term, count in counts.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return sum(v * b.get(k, 0.0) for k, v in a.items()) / (na * nb) if na and nb else 0.0


_TRAINED = [(intent, _vector(phrase)) for intent, phrases in EXAMPLES.items() for phrase in phrases]


def classify_intent(question: str) -> tuple[str, float]:
    query = _vector(question)
    scores: dict[str, float] = defaultdict(float)
    for intent, example in _TRAINED:
        scores[intent] = max(scores[intent], _cosine(query, example))
    intent, score = max(scores.items(), key=lambda pair: pair[1], default=("help", 0.0))
    return (intent, score) if score >= 0.16 else ("help", score)


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    conversation_id: str | None = Field(default=None, max_length=100)


def _fmt(value) -> str:
    number = float(value or 0)
    return f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}".rstrip("0").rstrip(".")


def _projects(cur) -> list[dict]:
    cur.execute("""
        SELECT p.project_id, p.project_code, p.name, p.status, p.start_date, p.end_date,
               d.name AS department, u.full_name AS project_head
        FROM projects p JOIN departments d ON d.department_id = p.department_id
        JOIN users u ON u.user_id = p.project_head_user_id
        ORDER BY CASE WHEN p.status = 'Active' THEN 0 ELSE 1 END, p.start_date, p.project_id
    """)
    return cur.fetchall()


def _project(cur, question: str) -> dict | None:
    rows = _projects(cur)
    text = question.casefold()
    for row in sorted(rows, key=lambda r: len(r["project_code"]), reverse=True):
        code = str(row["project_code"])
        if re.search(rf"(?<![a-z0-9]){re.escape(code.casefold())}(?![a-z0-9])", text):
            return row
    match = re.search(r"\bproject\s*(?:id|number|no\.?|#)?\s*#?(\d+)\b", text)
    if match:
        return next((r for r in rows if int(r["project_id"]) == int(match.group(1))), None)
    matches = [r for r in rows if len(str(r["name"])) >= 5 and str(r["name"]).casefold() in text]
    return max(matches, key=lambda r: len(str(r["name"])), default=None)


def _material(cur, question: str) -> tuple[dict | None, list[dict]]:
    cur.execute("SELECT material_id, material_code, name FROM materials ORDER BY LENGTH(name) DESC")
    rows = cur.fetchall()
    text = question.casefold()
    for row in rows:
        code = str(row["material_code"])
        if re.search(rf"(?<![a-z0-9]){re.escape(code.casefold())}(?![a-z0-9])", text):
            return row, []
    matches = [r for r in rows if len(str(r["name"])) >= 4 and str(r["name"]).casefold() in text]
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, matches[:5]
    terms = set(_tokens(question))
    ranked = []
    for row in rows:
        name_terms = set(_tokens(str(row["name"]))) - {"material", "stock"}
        overlap = terms & name_terms
        if overlap:
            ranked.append((len(overlap) / max(1, len(name_terms)), row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if ranked and ranked[0][0] >= 0.5:
        top = [r for score, r in ranked if score == ranked[0][0]]
        return (top[0], []) if len(top) == 1 else (None, top[:5])
    return None, []


def _need_entity(entity: str, choices: list[dict] | None = None) -> str:
    if choices:
        options = ", ".join(f"{r['material_code']} ({r['name']})" for r in choices)
        return f"I found multiple matching materials: {options}. Which one did you mean?"
    if entity == "project":
        return "Please include a project code or numeric project ID. You can also ask me to list ongoing projects."
    return "Please include a material code or a distinctive part of its name, such as ELE-001."


def _project_lines(cur, project_id: int) -> list[dict]:
    cur.execute("""
        WITH latest AS (
            SELECT DISTINCT ON (project_id) project_id, requirement_version_id
            FROM project_requirement_versions WHERE review_status = 'Approved'
            ORDER BY project_id, version_number DESC
        ), consumed_line AS (
            SELECT requirement_line_id, -SUM(quantity_delta) AS consumed
            FROM inventory_transactions WHERE transaction_type = 'Consumption' GROUP BY requirement_line_id
        ), consumed_allocation AS (
            SELECT allocation_id, -SUM(quantity_delta) AS consumed
            FROM inventory_transactions WHERE transaction_type = 'Consumption' GROUP BY allocation_id
        ), allocated_line AS (
            SELECT a.requirement_line_id,
                   SUM(GREATEST(0, a.allocated_quantity - a.transferred_out_quantity - COALESCE(c.consumed, 0))) AS remaining_allocated
            FROM inventory_allocations a LEFT JOIN consumed_allocation c USING (allocation_id)
            WHERE a.allocation_status = 'Active' GROUP BY a.requirement_line_id
        )
        SELECT m.material_code, m.name AS material_name, u.uom_code,
               SUM(r.approved_quantity) AS approved_quantity,
               SUM(COALESCE(c.consumed, 0)) AS consumed_quantity,
               SUM(COALESCE(a.remaining_allocated, 0)) AS remaining_allocated
        FROM latest v JOIN project_material_requirements r ON r.requirement_version_id = v.requirement_version_id
        JOIN materials m ON m.material_id = r.material_id
        JOIN units_of_measure u ON u.uom_id = m.base_uom_id
        LEFT JOIN consumed_line c ON c.requirement_line_id = r.requirement_line_id
        LEFT JOIN allocated_line a ON a.requirement_line_id = r.requirement_line_id
        WHERE v.project_id = %s
        GROUP BY m.material_code, m.name, u.uom_code ORDER BY m.material_code
    """, (project_id,))
    return cur.fetchall()


def _answer_project_lines(cur, project: dict, remaining: bool) -> tuple[str, list[str]]:
    rows = _project_lines(cur, int(project["project_id"]))
    if not rows:
        return f"No approved material requirements are recorded for {project['project_code']}.", ["project_material_requirements"]
    lines = []
    for row in rows:
        needed = max(0.0, float(row["approved_quantity"]) - float(row["consumed_quantity"]))
        if remaining:
            lines.append(f"{row['material_code']} {row['material_name']}: {_fmt(row['remaining_allocated'])} {row['uom_code']} still allocated; {_fmt(needed)} {row['uom_code']} still required after consumption.")
        else:
            lines.append(f"{row['material_code']} {row['material_name']}: approved {_fmt(row['approved_quantity'])} {row['uom_code']}; consumed {_fmt(row['consumed_quantity'])}; {_fmt(needed)} still required.")
    title = "Remaining project allocation" if remaining else "Approved project requirements"
    return f"{title} for {project['project_code']} - {project['name']}:\n" + "\n".join(lines), [
        "projects", "project_requirement_versions", "project_material_requirements", "inventory_allocations", "inventory_transactions"]


def _answer_stock(cur, material: dict) -> tuple[str, list[str]]:
    cur.execute(STOCK_CTE + """
        SELECT warehouse, material_code, material_name, uom_code, on_hand_quantity,
               reserved_quantity, available_quantity, reorder_point_quantity
        FROM stock WHERE material_id = %s ORDER BY warehouse
    """, (material["material_id"],))
    rows = cur.fetchall()
    if not rows:
        return f"No inventory row is recorded for {material['material_code']} ({material['name']}).", ["inventory"]
    total = lambda key: sum(float(r[key]) for r in rows)
    unit = rows[0]["uom_code"]
    details = [f"{r['warehouse']}: {_fmt(r['on_hand_quantity'])} on hand, {_fmt(r['reserved_quantity'])} reserved, {_fmt(r['available_quantity'])} available (reorder point {_fmt(r['reorder_point_quantity'])} {unit})" for r in rows]
    answer = f"{material['material_code']} - {material['name']}: {_fmt(total('on_hand_quantity'))} {unit} on hand, {_fmt(total('reserved_quantity'))} reserved, and {_fmt(total('available_quantity'))} available.\n" + "\n".join(details)
    return answer, ["inventory", "inventory_allocations", "materials", "warehouses"]


def _answer_shortages(cur, project: dict | None) -> tuple[str, list[str]]:
    rows = [r for r in compute_risk(cur, resolve_as_of(None), 0) if r["status"] in {"SHORT", "AT_RISK", "WATCH"}]
    if project:
        rows = [r for r in rows if int(r["project_id"]) == int(project["project_id"])]
    rows.sort(key=lambda r: ({"SHORT": 0, "AT_RISK": 1, "WATCH": 2}[r["status"]], r["need_by_date"]))
    if not rows:
        scope = f" for {project['project_code']}" if project else ""
        return f"No uncovered or order-dependent lines were found{scope}.", ["risk.shortages", "inventory", "purchase_orders"]
    lines = [f"{r['project_code']} - {r['material_code']} {r['material_name']}: {r['status']}, {_fmt(r['not_covered'])} {r['uom_code']} uncovered, need by {r['need_by_date']}" + (f" ({r['urgency']})" if r.get("urgency") else "") for r in rows[:8]]
    suffix = f"\nShowing 8 of {len(rows)} lines." if len(rows) > 8 else ""
    return "Shortage risks, ranked by severity and need date:\n" + "\n".join(lines) + suffix, ["projects", "project_material_requirements", "inventory", "inventory_allocations", "purchase_orders"]


def _answer_orders(cur, material: dict | None) -> tuple[str, list[str]]:
    params: list = [list(OPEN_PO_STATUSES)]
    filter_sql = ""
    if material:
        filter_sql = " AND m.material_id = %s"
        params.append(material["material_id"])
    cur.execute("""
        SELECT po.po_number, s.name AS supplier_name, po.status,
               l.ordered_quantity - l.received_quantity AS outstanding_quantity,
               l.expected_delivery_date, m.material_code, m.name AS material_name, u.uom_code
        FROM purchase_orders po JOIN suppliers s ON s.supplier_id = po.supplier_id
        JOIN purchase_order_lines l ON l.purchase_order_id = po.purchase_order_id
        JOIN materials m ON m.material_id = l.material_id
        JOIN units_of_measure u ON u.uom_id = m.base_uom_id
        WHERE po.status = ANY(%s) AND l.ordered_quantity > l.received_quantity""" + filter_sql + """
        ORDER BY l.expected_delivery_date, po.po_number LIMIT 12
    """, tuple(params))
    rows = cur.fetchall()
    if not rows:
        scope = f" for {material['material_code']}" if material else ""
        return f"No open purchase-order quantity is recorded{scope}.", ["purchase_orders", "suppliers"]
    lines = [f"{r['po_number']}: {r['material_code']} {_fmt(r['outstanding_quantity'])} {r['uom_code']} outstanding; {r['supplier_name']} expects {r['expected_delivery_date']} (status {r['status']})." for r in rows]
    return "Open purchase orders, earliest delivery first:\n" + "\n".join(lines), ["purchase_orders", "purchase_order_lines", "suppliers"]


def _answer_reorder(cur) -> tuple[str, list[str]]:
    cur.execute(STOCK_CTE + """, on_order AS (
        SELECT po.warehouse_id, l.material_id, SUM(l.ordered_quantity - l.received_quantity) AS qty,
               MIN(l.expected_delivery_date) AS next_expected
        FROM purchase_order_lines l JOIN purchase_orders po ON po.purchase_order_id = l.purchase_order_id
        WHERE po.status = ANY(%s) AND l.ordered_quantity > l.received_quantity
        GROUP BY po.warehouse_id, l.material_id
    )
    SELECT s.warehouse, s.material_code, s.material_name, s.uom_code, s.available_quantity,
           s.reorder_point_quantity, COALESCE(o.qty, 0) AS on_order_quantity, o.next_expected
    FROM stock s LEFT JOIN on_order o ON o.warehouse_id = s.warehouse_id AND o.material_id = s.material_id
    WHERE s.available_quantity <= s.reorder_point_quantity
    ORDER BY s.available_quantity - s.reorder_point_quantity, s.material_code LIMIT 12
    """, (list(OPEN_PO_STATUSES),))
    rows = cur.fetchall()
    if not rows:
        return "No inventory rows are at or below their reorder point.", ["inventory", "purchase_orders"]
    lines = [f"{r['warehouse']} - {r['material_code']} {r['material_name']}: {_fmt(r['available_quantity'])} {r['uom_code']} available (reorder point {_fmt(r['reorder_point_quantity'])}); {_fmt(r['on_order_quantity'])} on order; next expected {r['next_expected'] or 'date not set'}." for r in rows]
    return "Materials at or below reorder point:\n" + "\n".join(lines), ["inventory", "purchase_orders", "purchase_order_lines"]


def _answer_access(cur, project: dict | None) -> tuple[str, list[str]]:
    cur.execute("""
        SELECT u.full_name, r.role_code
        FROM users u JOIN roles r ON r.role_id = u.assigned_role_id
        WHERE u.account_status = 'Active' ORDER BY r.role_code, u.full_name LIMIT 20
    """)
    rows = cur.fetchall()
    scope = f" for {project['project_code']}" if project else ""
    cur.execute("SELECT COUNT(*) AS total FROM users u JOIN roles r ON r.role_id = u.assigned_role_id WHERE u.account_status = 'Active'")
    total = int(cur.fetchone()["total"])
    if not rows:
        return f"No Active accounts with assigned roles were found. In this prototype, every signed-in Active user with an assigned role can read inventory{scope}; access is not restricted per project.", ["users", "roles", "security.permissions_for"]
    names = ", ".join(f"{r['full_name']} ({r['role_code']})" for r in rows)
    suffix = f" Showing {len(rows)} of {total} Active users." if total > len(rows) else ""
    return f"There is no project-specific access list{scope}. Every signed-in Active user with an assigned role can read project and inventory data. Active users: {names}.{suffix}", ["users", "roles", "departments", "security.permissions_for"]


def _help() -> tuple[str, list[str]]:
    return ("I can answer about ongoing projects, project status and requirements, remaining allocations, stock, shortages, purchase orders, reorder points, and access. Try 'How much ELE-001 is available?' or 'What is left for project 12?'", [])


@router.post("/chat")
def chat(payload: ChatRequest, cur=Depends(db.get_cursor)):
    """Answer from live records; the assistant does not change inventory."""
    question = payload.question.strip()
    conversation_id = payload.conversation_id or str(uuid4())
    if not question:
        return {"conversation_id": conversation_id, "answer": "Please enter an inventory or project question.", "sources": []}
    intent, confidence = classify_intent(question)
    project = _project(cur, question) if intent in {"project_remaining", "project_requirements", "project_status", "shortages", "access"} else None
    material = None
    alternatives: list[dict] = []
    if intent in {"material_stock", "purchase_orders"}:
        material, alternatives = _material(cur, question)

    if intent == "active_projects":
        rows = [p for p in _projects(cur) if p["status"] == "Active"]
        answer = "There are no projects marked Active." if not rows else "Ongoing projects:\n" + "\n".join(f"{p['project_code']} - {p['name']} (ends {p['end_date']})" for p in rows)
        sources = ["projects"]
    elif intent == "project_status":
        answer = (f"{project['project_code']} - {project['name']} is {project['status']}. Department: {project['department']}; project head: {project['project_head']}; dates: {project['start_date']} to {project['end_date']}." if project else _need_entity("project"))
        sources = ["projects", "departments", "users"] if project else []
    elif intent in {"project_remaining", "project_requirements"}:
        answer, sources = _answer_project_lines(cur, project, intent == "project_remaining") if project else (_need_entity("project"), [])
    elif intent == "material_stock":
        answer, sources = _answer_stock(cur, material) if material else (_need_entity("material", alternatives), ["materials"])
    elif intent == "shortages":
        answer, sources = _answer_shortages(cur, project)
    elif intent == "purchase_orders":
        answer, sources = (_need_entity("material", alternatives), ["materials"]) if alternatives else _answer_orders(cur, material)
    elif intent == "reorder":
        answer, sources = _answer_reorder(cur)
    elif intent == "access":
        answer, sources = _answer_access(cur, project)
    else:
        answer, sources = _help()

    return {
        "conversation_id": conversation_id,
        "answer": f"{answer}\n\n{SYNTHETIC_NOTICE}",
        "sources": sources,
        "intent": intent,
        "intent_confidence": round(confidence, 3),
    }