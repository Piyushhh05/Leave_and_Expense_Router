"""
schema_spec.py - the DATA DICTIONARY, written once as Python data.

Three things are produced from this single description:
  1. sql/schema.sql          (MySQL tables)        -> python -m generator.schema_spec
  2. docs/data_dictionary.md (human readable)      -> python -m generator.schema_spec
  3. the checks in validate_data.py (required, enum, type, PK, FK, unique)

Because the validator reads the same description that produced the database
tables, the documentation can never drift away from what is enforced.

Type shorthand used below:
  str:N     VARCHAR(N)          int      INT
  dec:P,S   DECIMAL(P,S)        date     DATE
  bool      TINYINT(1) 0/1      text     TEXT
"""
import os

from generator import config as C

# ---------------------------------------------------------------------------
# Allowed values (enums) shared by several tables
# ---------------------------------------------------------------------------
ROLES = ["MANAGER", "SKIP_MANAGER", "HR_HEAD", "FINANCE_CONTROLLER", "CFO"]
LEAVE_STATUSES = ["SUBMITTED", "PENDING_APPROVAL", "APPROVED", "REJECTED"]
CLAIM_STATUSES = ["SUBMITTED", "PENDING_APPROVAL", "APPROVED", "REJECTED", "REIMBURSED"]
STEP_STATUSES = ["APPROVED", "REJECTED", "PENDING", "WAITING", "SKIPPED"]
EXPENSE_CATEGORIES = [p[1] for p in C.EXPENSE_POLICIES]

LEAVE_REASON_CODES = [
    "AWAITING_APPROVAL", "APPROVED_WITHIN_POLICY", "APPROVED_BY_OVERRIDE",
    "NO_WORKING_DAYS", "OVERLAPPING_LEAVE", "INSUFFICIENT_BALANCE", "EXCEEDS_MAX_CONSECUTIVE",
    "REJECTED_BY_APPROVER",
]
EXPENSE_REASON_CODES = [
    "AWAITING_APPROVAL", "APPROVED_WITHIN_POLICY", "APPROVED_POLICY_EXCEPTION",
    "APPROVED_BUDGET_EXCEPTION", "APPROVED_BY_OVERRIDE",
    "MISSING_COST_CENTER", "EXPENSE_OUTSIDE_EMPLOYMENT", "MISSING_RECEIPT",
    "DUPLICATE_RECEIPT_HASH", "POLICY_LIMIT_BREACH", "BUDGET_EXCEEDED", "REJECTED_BY_APPROVER",
]
STEP_REASON_CODES = [
    "APPROVED_WITHIN_POLICY", "APPROVED_POLICY_EXCEPTION", "APPROVED_BUDGET_EXCEPTION",
    "POLICY_LIMIT_BREACH", "BUDGET_EXCEEDED", "REJECTED_BY_APPROVER",
    "EARLIER_STEP_REJECTED", "SAME_APPROVER_EARLIER_STEP",
]
ALL_REASON_CODES = sorted(set(LEAVE_REASON_CODES + EXPENSE_REASON_CODES + STEP_REASON_CODES))

# Labels used in ground_truth.csv
INJECTED_ISSUES = [
    "NEGATIVE_LEAVE_BALANCE", "OVERLAPPING_APPROVED_LEAVE", "EXPENSE_OUTSIDE_EMPLOYMENT",
    "SPLIT_CLAIM_EVASION", "MISSING_COST_CENTER", "SELF_APPROVAL", "DUPLICATE_REIMBURSEMENT",
]
BASELINE_ISSUES = [
    "MISSING_RECEIPT", "DUPLICATE_RECEIPT_HASH", "POLICY_LIMIT_BREACH", "BUDGET_EXCEEDED",
    "INSUFFICIENT_BALANCE", "OVERLAPPING_LEAVE", "EXCEEDS_MAX_CONSECUTIVE", "NO_WORKING_DAYS",
    "WEEKEND_HOLIDAY_SPAN", "MULTI_LEVEL_APPROVAL", "BOUNDARY_AMOUNT",
]
ISSUE_TYPES = INJECTED_ISSUES + BASELINE_ISSUES


def col(name, type_, required=True, allowed=None, unit="", unique=False, rule="", pattern=None):
    """One column of the data dictionary."""
    return {"name": name, "type": type_, "required": required, "allowed": allowed,
            "unit": unit, "unique": unique, "rule": rule, "pattern": pattern}


# ---------------------------------------------------------------------------
# The tables. ORDER = parents first (this is also the load order).
# ---------------------------------------------------------------------------
TABLES = {
    "holidays": {
        "description": "Illustrative public holidays per country (used for business-day counts).",
        "pk": "holiday_id",
        "fks": [],
        "columns": [
            col("holiday_id", "str:8", pattern=r"^HOL-\d{3}$", unique=True, rule="HOL-001, HOL-002 ..."),
            col("holiday_date", "date", rule="Must fall inside the balance year"),
            col("country", "str:2", allowed=C.COUNTRIES),
            col("name", "str:60"),
        ],
    },
    "cost_centers": {
        "description": "Budget owners. Employees and expense claims are charged to a cost centre.",
        "pk": "cost_center_id",
        "fks": [],
        "columns": [
            col("cost_center_id", "str:10", pattern=r"^CC-\d{3}$", unique=True),
            col("name", "str:60"),
            col("country", "str:2", allowed=C.COUNTRIES),
            col("department", "str:20", allowed=C.DEPARTMENTS + ["Executive"]),
            col("annual_budget", "dec:12,2", unit="USD", rule="> 0; = headcount x BUDGET_PER_HEAD"),
        ],
    },
    "employees": {
        "description": "Employee master with the reporting hierarchy (manager_id points to another employee).",
        "pk": "employee_id",
        "fks": [("manager_id", "employees", "employee_id"), ("cost_center_id", "cost_centers", "cost_center_id")],
        "columns": [
            col("employee_id", "str:10", pattern=r"^EMP-\d{6}$", unique=True),
            col("full_name", "str:60"),
            col("email", "str:80", unique=True, rule="Unique; uses the reserved example.com domain"),
            col("country", "str:2", allowed=C.COUNTRIES),
            col("department", "str:20", allowed=C.DEPARTMENTS + ["Executive"]),
            col("job_level", "int", allowed=["1", "2", "3", "4", "5"], rule="1 Associate, 2 Manager, 3 Director, 4 VP, 5 CEO"),
            col("job_title", "str:30"),
            col("manager_id", "str:10", required=False, rule="Empty only for the CEO; manager must have a higher job_level"),
            col("cost_center_id", "str:10"),
            col("hire_date", "date", rule="Not after the dataset as-of date"),
            col("termination_date", "date", required=False, rule="Empty for ACTIVE; >= hire_date for TERMINATED"),
            col("status", "str:12", allowed=["ACTIVE", "TERMINATED"]),
            col("special_role", "str:20", required=False,
                allowed=["FINANCE_CONTROLLER", "CFO", "HR_HEAD"], unique=False,
                rule="Designated approver roles. Exactly one employee per role"),
        ],
    },
    "leave_policies": {
        "description": "Six leave policies. LPOL-03 covers both UK and DE (see applies_to_countries).",
        "pk": "leave_policy_id",
        "fks": [],
        "columns": [
            col("leave_policy_id", "str:10", pattern=r"^LPOL-\d{2}$", unique=True),
            col("name", "str:60"),
            col("leave_type", "str:10", allowed=["ANNUAL", "SICK", "CASUAL", "UNPAID"]),
            col("applies_to_countries", "str:10", rule="ALL, one country code, or codes joined by |"),
            col("annual_days", "dec:6,2", unit="days", rule=">= 0"),
            col("accrual_per_month", "dec:6,2", unit="days", rule=">= 0; annual_days / 12 or close"),
            col("carry_forward_cap", "dec:6,2", unit="days", rule=">= 0"),
            col("max_consecutive_days", "int", unit="business days", rule="> 0"),
            col("deducts_balance", "bool", rule="0 for unpaid leave (no balance check)"),
            col("effective_from", "date"),
            col("effective_to", "date", required=False, rule="Empty = still in force"),
        ],
    },
    "leave_balances": {
        "description": "BRIDGE table between employees and leave policies (N:M) holding one balance per year.",
        "pk": "leave_balance_id",
        "fks": [("employee_id", "employees", "employee_id"), ("leave_policy_id", "leave_policies", "leave_policy_id")],
        "unique_together": ["employee_id", "leave_policy_id", "balance_year"],
        "columns": [
            col("leave_balance_id", "str:20", pattern=r"^LBAL-\d{4}-\d{6}$", unique=True),
            col("employee_id", "str:10"),
            col("leave_policy_id", "str:10"),
            col("balance_year", "int", rule="= 2026"),
            col("opening_balance", "dec:6,2", unit="days", rule="Carry forward, 0 <= x <= carry_forward_cap"),
            col("accrued_days", "dec:6,2", unit="days", rule="= min(annual_days, accrual_per_month x months accrued)"),
            col("used_days", "dec:6,2", unit="days", rule="= sum of business_days of APPROVED requests"),
            col("pending_days", "dec:6,2", unit="days", rule="= sum of business_days of PENDING_APPROVAL requests"),
            col("available_days", "dec:6,2", unit="days", rule="= opening + accrued - used - pending (negative = anomaly)"),
            col("as_of_date", "date", rule="Date the balance was calculated"),
        ],
    },
    "expense_policies": {
        "description": "One expense policy per category: per-line limit and receipt rule.",
        "pk": "expense_policy_id",
        "fks": [],
        "columns": [
            col("expense_policy_id", "str:10", pattern=r"^EPOL-\d{2}$", unique=True),
            col("category", "str:25", allowed=EXPENSE_CATEGORIES, unique=True),
            col("max_line_amount", "dec:12,2", unit="USD", rule="> 0; a line above this is a policy limit breach"),
            col("receipt_required_above", "dec:12,2", unit="USD", rule=">= 0; lines above this need a receipt"),
            col("effective_from", "date"),
            col("effective_to", "date", required=False),
        ],
    },
    "approval_rules": {
        "description": "Routing rules (data, not code). The router reads these to decide who must approve.",
        "pk": "approval_rule_id",
        "fks": [],
        "columns": [
            col("approval_rule_id", "str:10", pattern=r"^APRL-[LE]\d$", unique=True),
            col("domain", "str:10", allowed=["LEAVE", "EXPENSE"]),
            col("step_role", "str:20", allowed=ROLES),
            col("condition_type", "str:20", allowed=[
                "ALWAYS", "DAYS_ABOVE", "LEAVE_TYPE", "AMOUNT_ABOVE", "CATEGORY",
                "COUNTRY_AMOUNT", "POLICY_BREACH", "BUDGET_EXCEEDED"]),
            col("threshold", "dec:12,2", required=False, rule="Days or USD depending on condition_type"),
            col("match_value", "str:30", required=False, rule="Leave type, category or countries joined by |"),
            col("min_approver_level", "int", allowed=["2", "3", "4"], rule="Approver's job_level must be at least this"),
            col("effective_from", "date"),
            col("effective_to", "date", required=False),
            col("description", "str:120"),
        ],
    },
    "leave_requests": {
        "description": "A request for time off. Status changes are NOT overwritten silently: see status_events.",
        "pk": "leave_request_id",
        "fks": [("employee_id", "employees", "employee_id"), ("leave_policy_id", "leave_policies", "leave_policy_id")],
        "columns": [
            col("leave_request_id", "str:20", pattern=r"^LVE-\d{4}-\d{6}$", unique=True),
            col("employee_id", "str:10"),
            col("leave_policy_id", "str:10"),
            col("start_date", "date"),
            col("end_date", "date", rule=">= start_date"),
            col("calendar_days", "int", unit="days", rule="= end_date - start_date + 1"),
            col("business_days", "int", unit="days", rule="Weekdays in range minus country public holidays"),
            col("submitted_date", "date", rule="<= start_date"),
            col("request_reason", "str:80"),
            col("balance_at_submission", "dec:6,2", required=False, unit="days",
                rule="Available balance when submitted. Empty for unpaid leave"),
            col("status", "str:20", allowed=LEAVE_STATUSES),
            col("final_reason_code", "str:30", allowed=LEAVE_REASON_CODES),
            col("final_decision_date", "date", required=False, rule="Empty while pending"),
        ],
    },
    "expense_claims": {
        "description": "Header of an expense claim. total_amount and line_count are derived from expense_lines.",
        "pk": "expense_claim_id",
        "fks": [("employee_id", "employees", "employee_id"), ("cost_center_id", "cost_centers", "cost_center_id")],
        "columns": [
            col("expense_claim_id", "str:20", pattern=r"^EXP-\d{4}-\d{6}$", unique=True),
            col("employee_id", "str:10"),
            col("cost_center_id", "str:10", required=False, rule="Required by policy. Empty = anomaly MISSING_COST_CENTER"),
            col("employee_country", "str:2", allowed=C.COUNTRIES, rule="Country of the employee when submitted (used for routing)"),
            col("submitted_date", "date"),
            col("purpose", "str:80"),
            col("currency", "str:3", allowed=["USD"], rule="Single reporting currency, no FX"),
            col("total_amount", "dec:12,2", unit="USD", rule="= sum of line amounts"),
            col("line_count", "int", rule="= number of lines, 1 to 10"),
            col("has_policy_breach", "bool", rule="1 if any line is above its policy limit"),
            col("budget_exceeded", "bool", rule="1 if approving would push the cost centre over budget"),
            col("status", "str:20", allowed=CLAIM_STATUSES),
            col("final_reason_code", "str:30", allowed=EXPENSE_REASON_CODES),
            col("final_decision_date", "date", required=False, rule="Empty while pending"),
        ],
    },
    "expense_lines": {
        "description": "Line items of a claim with receipt metadata.",
        "pk": "expense_line_id",
        "fks": [("expense_claim_id", "expense_claims", "expense_claim_id"),
                ("expense_policy_id", "expense_policies", "expense_policy_id")],
        "unique_together": ["expense_claim_id", "line_no"],
        "columns": [
            col("expense_line_id", "str:40", pattern=r"^EXPL-EXP-\d{4}-\d{6}-\d{2}$", unique=True),
            col("expense_claim_id", "str:20"),
            col("line_no", "int", rule="1..10, no gaps inside a claim"),
            col("expense_policy_id", "str:10", rule="Policy of the category of this line"),
            col("expense_date", "date", rule="Within the employee's employment dates"),
            col("merchant", "str:60"),
            col("amount", "dec:12,2", unit="USD", rule="> 0"),
            col("receipt_provided", "bool"),
            col("receipt_file_name", "str:40", required=False, rule="Empty when no receipt"),
            col("receipt_hash", "str:16", required=False, rule="Fingerprint of the receipt file. Same hash twice = duplicate receipt"),
        ],
    },
    "approval_steps": {
        "description": "BRIDGE between a request and the rules that apply to it: one row per approver step.",
        "pk": "approval_step_id",
        "fks": [("leave_request_id", "leave_requests", "leave_request_id"),
                ("expense_claim_id", "expense_claims", "expense_claim_id"),
                ("approval_rule_id", "approval_rules", "approval_rule_id"),
                ("approver_id", "employees", "employee_id")],
        "checks": ["(leave_request_id IS NULL) <> (expense_claim_id IS NULL)"],
        "unique_together": ["approval_step_id"],
        "columns": [
            col("approval_step_id", "str:40", pattern=r"^APR-(LVE|EXP)-\d{4}-\d{6}-\d{2}$", unique=True),
            col("leave_request_id", "str:20", required=False, rule="Exactly one of leave_request_id / expense_claim_id is set"),
            col("expense_claim_id", "str:20", required=False),
            col("step_no", "int", rule="1, 2, 3 ... in order"),
            col("approval_rule_id", "str:10", rule="The rule that first required this role"),
            col("approver_role", "str:20", allowed=ROLES),
            col("approver_id", "str:10", rule="Must not be the requester; job_level >= rule.min_approver_level"),
            col("status", "str:10", allowed=STEP_STATUSES),
            col("decided_date", "date", required=False, rule="Set only when status is APPROVED or REJECTED"),
            col("routing_reason", "str:200", rule="Why this step exists (rule + facts)"),
            col("decision_reason_code", "str:30", required=False, allowed=STEP_REASON_CODES),
            col("decision_reason", "str:200", required=False, rule="Human readable reason of the decision"),
        ],
    },
    "reimbursements": {
        "description": "Payment records. Created only after a claim has been fully approved.",
        "pk": "reimbursement_id",
        "fks": [("expense_claim_id", "expense_claims", "expense_claim_id"), ("employee_id", "employees", "employee_id")],
        "columns": [
            col("reimbursement_id", "str:20", pattern=r"^RMB-\d{4}-\d{6}$", unique=True),
            col("expense_claim_id", "str:20", rule="Claim must be APPROVED or REIMBURSED. One payment per claim"),
            col("employee_id", "str:10", rule="Same employee as the claim"),
            col("amount", "dec:12,2", unit="USD", rule="= claim total_amount"),
            col("currency", "str:3", allowed=["USD"]),
            col("payment_method", "str:15", allowed=["BANK_TRANSFER", "PAYROLL"]),
            col("approved_date", "date", rule="= claim final_decision_date"),
            col("payment_date", "date", rule=">= approved_date"),
            col("status", "str:10", allowed=["PAID", "SCHEDULED"], rule="PAID if payment_date <= as-of date"),
        ],
    },
    "status_events": {
        "description": "Append-only history of every status change of a request or claim. Nothing is overwritten.",
        "pk": "event_id",
        "fks": [("leave_request_id", "leave_requests", "leave_request_id"),
                ("expense_claim_id", "expense_claims", "expense_claim_id"),
                ("actor_id", "employees", "employee_id")],
        "checks": ["(leave_request_id IS NULL) <> (expense_claim_id IS NULL)"],
        "columns": [
            col("event_id", "str:10", pattern=r"^EVT-\d{6}$", unique=True),
            col("leave_request_id", "str:20", required=False, rule="Exactly one of the two request columns is set"),
            col("expense_claim_id", "str:20", required=False),
            col("from_status", "str:20", required=False, allowed=CLAIM_STATUSES, rule="Empty for the first event"),
            col("to_status", "str:20", allowed=CLAIM_STATUSES),
            col("event_date", "date"),
            col("actor_type", "str:10", allowed=["SYSTEM", "EMPLOYEE"]),
            col("actor_id", "str:10", required=False, rule="Empty when actor_type is SYSTEM"),
            col("reason_code", "str:30", allowed=ALL_REASON_CODES),
            col("note", "str:200", required=False),
        ],
    },
    # ---- not "input" tables: answer key and detector output ----------------
    "ground_truth": {
        "description": "ANSWER KEY. Known anomalies and expected decisions. Never used as an input feature.",
        "pk": "ground_truth_id",
        "fks": [],
        "columns": [
            col("ground_truth_id", "str:10", pattern=r"^GT-\d{6}$", unique=True),
            col("entity_type", "str:20", allowed=["LEAVE_REQUEST", "EXPENSE_CLAIM", "LEAVE_BALANCE"]),
            col("entity_id", "str:40", rule="ID of the labelled record (checked against the tables by the validator)"),
            col("issue_type", "str:30", allowed=ISSUE_TYPES),
            col("origin", "str:15", allowed=["INJECTED", "BASELINE_RULE"],
                rule="INJECTED = deliberately planted; BASELINE_RULE = label derived from the documented rules"),
            col("expected_decision", "str:40", rule="What a correct control should have done"),
            col("group_id", "str:20", required=False, rule="Links records of one scenario (e.g. split claims)"),
            col("notes", "str:200", required=False),
        ],
    },
    "detected_exceptions": {
        "description": "OUTPUT of the audit detectors (detectors.py). They only read the input tables.",
        "pk": "detection_id",
        "fks": [],
        "columns": [
            col("detection_id", "str:10", pattern=r"^DET-\d{6}$", unique=True),
            col("entity_type", "str:20", allowed=["LEAVE_REQUEST", "EXPENSE_CLAIM", "LEAVE_BALANCE"]),
            col("entity_id", "str:40"),
            col("issue_type", "str:30", allowed=ISSUE_TYPES),
            col("detail", "str:200", rule="Human readable explanation of why it was flagged"),
        ],
    },
}

# Tables loaded into the database in this order (parents first)
LOAD_ORDER = list(TABLES.keys())
# Tables that are plain input data (ground truth and detections are separate)
INPUT_TABLES = [t for t in LOAD_ORDER if t not in ("ground_truth", "detected_exceptions")]

# Documented relationships (for the README / data dictionary)
RELATIONSHIPS = [
    ("employees", "employees", "1:N, optional", "manager_id", "A manager has many reports. The CEO has no manager."),
    ("cost_centers", "employees", "1:N", "cost_center_id", "An employee is charged to one cost centre."),
    ("employees", "leave_policies", "N:M via leave_balances", "employee_id + leave_policy_id", "One balance row per employee, policy and year."),
    ("employees", "leave_requests", "1:N", "employee_id", "One employee raises many requests."),
    ("leave_policies", "leave_requests", "1:N", "leave_policy_id", "Each request is of one leave type/policy."),
    ("employees", "expense_claims", "1:N", "employee_id", "One employee raises many claims."),
    ("cost_centers", "expense_claims", "1:N, optional", "cost_center_id", "Optional in the table so the missing-cost-centre anomaly can be stored and labelled."),
    ("expense_claims", "expense_lines", "1:N (1 to 10)", "expense_claim_id", "A claim has 1 to 10 lines."),
    ("expense_policies", "expense_lines", "1:N", "expense_policy_id", "Each line is governed by its category policy."),
    ("leave_requests / expense_claims", "approval_steps", "1:N (one of two, optional each)", "leave_request_id / expense_claim_id", "Steps belong to exactly one request."),
    ("approval_rules", "approval_steps", "1:N  (so requests <-> rules is N:M via approval_steps)", "approval_rule_id", "Which rule produced the step."),
    ("employees", "approval_steps", "1:N", "approver_id", "The person who must decide the step."),
    ("expense_claims", "reimbursements", "1:0..1 (1:N only for the duplicate-reimbursement anomaly)", "expense_claim_id", "Created only after final approval."),
    ("leave_requests / expense_claims", "status_events", "1:N", "leave_request_id / expense_claim_id", "Append-only status history."),
]

LIFECYCLES = {
    "Leave request": "(none) -> SUBMITTED -> PENDING_APPROVAL -> APPROVED | REJECTED.  SUBMITTED -> REJECTED is a system screening rejection.",
    "Expense claim": "(none) -> SUBMITTED -> PENDING_APPROVAL -> APPROVED -> REIMBURSED.  Also SUBMITTED -> REJECTED (screening) and PENDING_APPROVAL -> REJECTED.",
    "Approval step": "WAITING -> PENDING -> APPROVED | REJECTED.  Steps after a rejection become SKIPPED.",
    "Reimbursement": "SCHEDULED -> PAID (by payment_date).",
}


# ---------------------------------------------------------------------------
# Helpers that turn the description into SQL and Markdown
# ---------------------------------------------------------------------------
def column_names(table):
    return [c["name"] for c in TABLES[table]["columns"]]


def mysql_type(column):
    """Translate the shorthand type into a MySQL column type."""
    kind = column["type"]
    if column["allowed"] and kind.startswith("str:"):
        values = ", ".join("'" + v + "'" for v in column["allowed"])
        return f"ENUM({values})"
    if kind.startswith("str:"):
        return "VARCHAR(" + kind.split(":")[1] + ")"
    if kind.startswith("dec:"):
        return "DECIMAL(" + kind.split(":")[1] + ")"
    return {"int": "INT", "date": "DATE", "bool": "TINYINT(1)", "text": "TEXT"}[kind]


def build_schema_sql():
    lines = ["-- MySQL schema generated from generator/schema_spec.py", "-- Re-create with: python -m generator.schema_spec", "",
             "SET FOREIGN_KEY_CHECKS = 0;"]
    for table in reversed(LOAD_ORDER):
        lines.append(f"DROP TABLE IF EXISTS {table};")
    lines.append("SET FOREIGN_KEY_CHECKS = 1;")
    lines.append("")
    for table in LOAD_ORDER:
        spec = TABLES[table]
        parts = []
        for c in spec["columns"]:
            null = "NOT NULL" if c["required"] else "NULL"
            parts.append(f"  {c['name']} {mysql_type(c)} {null}")
        parts.append(f"  PRIMARY KEY ({spec['pk']})")
        for c in spec["columns"]:
            if c["unique"] and c["name"] != spec["pk"]:
                parts.append(f"  UNIQUE KEY uq_{table}_{c['name']} ({c['name']})")
        if spec.get("unique_together") and len(spec["unique_together"]) > 1:
            cols = ", ".join(spec["unique_together"])
            parts.append(f"  UNIQUE KEY uq_{table}_combo ({cols})")
        for column, parent, parent_col in spec["fks"]:
            parts.append(f"  CONSTRAINT fk_{table}_{column} FOREIGN KEY ({column}) REFERENCES {parent} ({parent_col})")
        for i, check in enumerate(spec.get("checks", []), start=1):
            parts.append(f"  CONSTRAINT ck_{table}_{i} CHECK ({check})")
        lines.append(f"CREATE TABLE {table} (")
        lines.append(",\n".join(parts))
        lines.append(") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;")
        lines.append("")
    return "\n".join(lines)


def build_data_dictionary_md():
    out = ["# Data dictionary", "",
           "Generated from `generator/schema_spec.py` (`python -m generator.schema_spec`). "
           "The validator enforces exactly what is written here.", "",
           "Money is always **USD** (one reporting currency, no FX). Leave quantities are in **days**.", ""]
    out += ["## Relationships and cardinality", "",
            "| Parent | Child | Cardinality | Key | Note |", "|---|---|---|---|---|"]
    for parent, child, card, key, note in RELATIONSHIPS:
        out.append(f"| {parent} | {child} | {card} | `{key}` | {note} |")
    out += ["", "## Lifecycle states", ""]
    for name, text in LIFECYCLES.items():
        out.append(f"- **{name}**: {text}")
    out.append("")
    for table in LOAD_ORDER:
        spec = TABLES[table]
        out += [f"## {table}", "", spec["description"], "", f"Primary key: `{spec['pk']}`", ""]
        if spec["fks"]:
            out.append("Foreign keys: " + ", ".join(f"`{c}` -> `{p}.{pc}`" for c, p, pc in spec["fks"]))
            out.append("")
        out += ["| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |",
                "|---|---|---|---|---|---|---|"]
        for c in spec["columns"]:
            allowed = ", ".join(c["allowed"]) if c["allowed"] else (f"pattern `{c['pattern']}`" if c["pattern"] else "")
            allowed = allowed.replace("|", "\\|")
            rule = c["rule"].replace("|", "\\|")
            out.append(f"| `{c['name']}` | {c['type']} | {'yes' if c['required'] else 'no'} | {allowed} | "
                       f"{c['unit']} | {'yes' if c['unique'] else ''} | {rule} |")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "sql", "schema.sql"), "w", encoding="utf-8") as f:
        f.write(build_schema_sql())
    with open(os.path.join(root, "docs", "data_dictionary.md"), "w", encoding="utf-8") as f:
        f.write(build_data_dictionary_md())
    print("Wrote sql/schema.sql and docs/data_dictionary.md")
