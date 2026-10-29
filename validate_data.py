"""
validate_data.py - STEP 8: structural validation of the generated data.

    python validate_data.py            (checks ./data, writes docs/validation_summary.md)

Checks: primary keys, foreign keys, enums, types, patterns, uniqueness, date ordering,
arithmetic reconciliation, lifecycle consistency. It reads only the CSV files.
Business-rule exceptions (e.g. self-approval) are NOT errors here - audit_rules.py handles them.
"""
import os
import re
import sys
from datetime import date

from generator import config as C
from generator import schema_spec as S
from generator.helpers import count_days, holiday_dates, read_csv

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")


class Report:
    """Collects check results: (name, list of problems). Empty list = passed."""

    def __init__(self):
        self.results = []

    def check(self, name, problems):
        self.results.append((name, list(problems)))

    @property
    def failed(self):
        return [r for r in self.results if r[1]]


def load(data_dir):
    return {t: read_csv(os.path.join(data_dir, t + ".csv")) for t in S.LOAD_ORDER if t != "detected_exceptions"}


# ---------------------------------------------------------------------------
# Part 1: generic checks driven by the data dictionary
# ---------------------------------------------------------------------------
def check_value(column, value):
    """Returns a problem text or None for one non-empty cell."""
    kind = column["type"]
    try:
        if kind == "int":
            int(value)
        elif kind.startswith("dec:"):
            float(value)
        elif kind == "date":
            date.fromisoformat(value)
        elif kind == "bool":
            if value not in ("0", "1"):
                return "not 0/1"
        elif kind.startswith("str:") and len(value) > int(kind.split(":")[1]):
            return "longer than " + kind.split(":")[1]
    except ValueError:
        return f"not a valid {kind}"
    if column["allowed"] and value not in column["allowed"]:
        return "not an allowed value"
    if column["pattern"] and not re.match(column["pattern"], value):
        return "does not match pattern " + column["pattern"]
    return None


def generic_checks(data, report):
    keys = {t: {r[S.TABLES[t]["pk"]] for r in rows} for t, rows in data.items()}
    for table, rows in data.items():
        spec = S.TABLES[table]
        header = list(rows[0].keys()) if rows else []
        report.check(f"{table}: columns match the data dictionary", [] if header == S.column_names(table) else [str(header)])

        problems = []
        for row in rows:
            for column in spec["columns"]:
                value = row[column["name"]]
                if value == "":
                    if column["required"]:
                        problems.append(f"{row[spec['pk']]}: {column['name']} is empty but required")
                    continue
                issue = check_value(column, value)
                if issue:
                    problems.append(f"{row[spec['pk']]}: {column['name']}={value!r} {issue}")
        report.check(f"{table}: required / type / enum / pattern", problems)

        pks = [r[spec["pk"]] for r in rows]
        problems = [f"duplicate {spec['pk']} {p}" for p in set(pks) if pks.count(p) > 1] if len(pks) != len(set(pks)) else []
        report.check(f"{table}: primary key {spec['pk']} unique", problems)

        problems = []
        for column in spec["columns"]:
            if column["unique"] and column["name"] != spec["pk"]:
                values = [r[column["name"]] for r in rows if r[column["name"]] != ""]
                if len(values) != len(set(values)):
                    problems.append(column["name"] + " has duplicates")
        combo = spec.get("unique_together")
        if combo and len(combo) > 1:
            values = [tuple(r[c] for c in combo) for r in rows]
            if len(values) != len(set(values)):
                problems.append(" + ".join(combo) + " has duplicates")
        report.check(f"{table}: unique columns", problems)

        problems = []
        for column, parent, parent_column in spec["fks"]:
            for row in rows:
                value = row[column]
                if value != "" and value not in keys[parent]:
                    problems.append(f"{row[spec['pk']]}: {column}={value} not found in {parent}")
        report.check(f"{table}: foreign keys exist", problems)

        if table in ("approval_steps", "status_events"):
            problems = [r[spec["pk"]] for r in rows if (r["leave_request_id"] == "") == (r["expense_claim_id"] == "")]
            report.check(f"{table}: exactly one of leave_request_id / expense_claim_id", problems)


# ---------------------------------------------------------------------------
# Part 2: relationships between tables
# ---------------------------------------------------------------------------
def employee_checks(data, report):
    emp = {e["employee_id"]: e for e in data["employees"]}
    problems = []
    for e in emp.values():
        if e["manager_id"]:
            if int(emp[e["manager_id"]]["job_level"]) <= int(e["job_level"]):
                problems.append(f"{e['employee_id']}: manager is not senior")
        elif e["job_level"] != "5":
            problems.append(f"{e['employee_id']}: no manager but not the CEO")
        if e["status"] == "TERMINATED" and not e["termination_date"]:
            problems.append(f"{e['employee_id']}: TERMINATED without date")
        if e["status"] == "ACTIVE" and e["termination_date"]:
            problems.append(f"{e['employee_id']}: ACTIVE with termination date")
        if e["termination_date"] and e["termination_date"] < e["hire_date"]:
            problems.append(f"{e['employee_id']}: terminated before hire")
        if e["hire_date"] > C.AS_OF_DATE.isoformat():
            problems.append(f"{e['employee_id']}: hired after as-of date")
    report.check("employees: hierarchy, status and dates", problems)

    holders = [e["special_role"] for e in emp.values() if e["special_role"]]
    report.check("employees: exactly one holder per special role",
                 [r for r in ("CFO", "HR_HEAD", "FINANCE_CONTROLLER") if holders.count(r) != 1])

    budget_problems = []
    headcount = {}
    for e in emp.values():
        headcount[e["cost_center_id"]] = headcount.get(e["cost_center_id"], 0) + 1
    for cc in data["cost_centers"]:
        if float(cc["annual_budget"]) != headcount.get(cc["cost_center_id"], 0) * C.BUDGET_PER_HEAD:
            budget_problems.append(cc["cost_center_id"])
    report.check("cost_centers: budget = headcount x per-head amount", budget_problems)


def leave_checks(data, report):
    emp = {e["employee_id"]: e for e in data["employees"]}
    pol = {p["leave_policy_id"]: p for p in data["leave_policies"]}
    holidays = {c: holiday_dates([{"holiday_date": date.fromisoformat(h["holiday_date"]), "country": h["country"]}
                                  for h in data["holidays"]], c) for c in C.COUNTRIES}
    problems_dates, problems_days, problems_policy = [], [], []
    for r in data["leave_requests"]:
        rid, e = r["leave_request_id"], emp[r["employee_id"]]
        start, end, sub = (date.fromisoformat(r[k]) for k in ("start_date", "end_date", "submitted_date"))
        if not (sub <= start <= end):
            problems_dates.append(f"{rid}: dates out of order")
        if start < date.fromisoformat(e["hire_date"]) or (e["termination_date"] and end > date.fromisoformat(e["termination_date"])):
            problems_dates.append(f"{rid}: outside employment")
        if r["final_decision_date"] and date.fromisoformat(r["final_decision_date"]) < sub:
            problems_dates.append(f"{rid}: decided before submitted")
        if sub > C.AS_OF_DATE:
            problems_dates.append(f"{rid}: submitted after as-of date")
        calendar, business = count_days(start, end, holidays[e["country"]])
        if calendar != int(r["calendar_days"]) or business != int(r["business_days"]):
            problems_days.append(f"{rid}: days {r['calendar_days']}/{r['business_days']} expected {calendar}/{business}")
        applies = pol[r["leave_policy_id"]]["applies_to_countries"]
        if applies != "ALL" and e["country"] not in applies.split("|"):
            problems_policy.append(f"{rid}: policy {r['leave_policy_id']} does not apply to {e['country']}")
    report.check("leave_requests: date ordering and employment window", problems_dates)
    report.check("leave_requests: calendar and business days recomputed (weekends + holidays)", problems_days)
    report.check("leave_requests: policy applies to the employee's country", problems_policy)

    # balances: every figure re-derived from requests / policy / hire date
    used, pending = {}, {}
    for r in data["leave_requests"]:
        key = (r["employee_id"], r["leave_policy_id"])
        if r["status"] == "APPROVED":
            used[key] = used.get(key, 0) + int(r["business_days"])
        elif r["status"] == "PENDING_APPROVAL":
            pending[key] = pending.get(key, 0) + int(r["business_days"])
    from generator.rules import accrued_days, months_accrued
    problems = []
    for b in data["leave_balances"]:
        e, p = emp[b["employee_id"]], pol[b["leave_policy_id"]]
        key = (b["employee_id"], b["leave_policy_id"])
        term = date.fromisoformat(e["termination_date"]) if e["termination_date"] else None
        months = months_accrued(date.fromisoformat(e["hire_date"]), term, C.AS_OF_DATE)
        accrued = accrued_days(p["annual_days"], p["accrual_per_month"], months)
        expect = float(b["opening_balance"]) + accrued - used.get(key, 0) - pending.get(key, 0)
        if float(b["accrued_days"]) != accrued:
            problems.append(f"{b['leave_balance_id']}: accrued {b['accrued_days']} expected {accrued}")
        if float(b["used_days"]) != used.get(key, 0) or float(b["pending_days"]) != pending.get(key, 0):
            problems.append(f"{b['leave_balance_id']}: used/pending do not match requests")
        if abs(float(b["available_days"]) - expect) > 0.001:
            problems.append(f"{b['leave_balance_id']}: available {b['available_days']} expected {expect}")
        if float(b["opening_balance"]) > float(p["carry_forward_cap"]):
            problems.append(f"{b['leave_balance_id']}: opening above carry-forward cap")
    report.check("leave_balances: opening + accrued - used - pending = available (and accrual formula)", problems)


def expense_checks(data, report):
    emp = {e["employee_id"]: e for e in data["employees"]}
    pol = {p["expense_policy_id"]: p for p in data["expense_policies"]}
    lines_by_claim = {}
    for l in data["expense_lines"]:
        lines_by_claim.setdefault(l["expense_claim_id"], []).append(l)
    from generator.rules import worst_line_status
    problems_sum, problems_lines, problems_dates, problems_receipt, problems_ids = [], [], [], [], []
    for c in data["expense_claims"]:
        cid = c["expense_claim_id"]
        lines = lines_by_claim.get(cid, [])
        total = round(sum(float(l["amount"]) for l in lines), 2)
        if abs(total - float(c["total_amount"])) > 0.001:
            problems_sum.append(f"{cid}: total {c['total_amount']} but lines sum to {total}")
        numbers = sorted(int(l["line_no"]) for l in lines)
        if numbers != list(range(1, len(lines) + 1)) or not 1 <= len(lines) <= 10 or int(c["line_count"]) != len(lines):
            problems_lines.append(f"{cid}: line numbers / count wrong")
        worst = worst_line_status([{"amount": l["amount"], "expense_policy_id": l["expense_policy_id"]} for l in lines], pol)
        if (worst != "WITHIN") != (c["has_policy_breach"] == "1"):
            problems_lines.append(f"{cid}: has_policy_breach flag does not match lines")
        if c["employee_country"] != emp[c["employee_id"]]["country"]:
            problems_lines.append(f"{cid}: employee_country differs from employee")
        sub = date.fromisoformat(c["submitted_date"])
        if sub > C.AS_OF_DATE or (c["final_decision_date"] and date.fromisoformat(c["final_decision_date"]) < sub):
            problems_dates.append(f"{cid}: submitted/decided date problem")
        for l in lines:
            if date.fromisoformat(l["expense_date"]) > sub:
                problems_dates.append(f"{l['expense_line_id']}: expense date after submission")
            if l["expense_line_id"] != f"EXPL-{cid}-{int(l['line_no']):02d}":
                problems_ids.append(f"{l['expense_line_id']}: id does not follow EXPL-<claim>-NN")
            if (l["receipt_provided"] == "1") != bool(l["receipt_hash"] and l["receipt_file_name"]):
                problems_receipt.append(f"{l['expense_line_id']}: receipt fields inconsistent")
    report.check("expense_claims: total = sum of lines", problems_sum)
    report.check("expense_claims: line count 1-10, numbering, breach flag, country", problems_lines)
    report.check("expense_claims / lines: date ordering", problems_dates)
    report.check("expense_lines: receipt metadata consistent; id format", problems_receipt + problems_ids)


def approval_checks(data, report):
    leave = {r["leave_request_id"]: r for r in data["leave_requests"]}
    claim = {c["expense_claim_id"]: c for c in data["expense_claims"]}
    steps = {}
    for s in data["approval_steps"]:
        steps.setdefault(s["leave_request_id"] or s["expense_claim_id"], []).append(s)
    problems_order, problems_status, problems_dates, problems_ids = [], [], [], []
    for request_id, rows in steps.items():
        rows.sort(key=lambda s: int(s["step_no"]))
        parent = leave.get(request_id) or claim[request_id]
        if [int(s["step_no"]) for s in rows] != list(range(1, len(rows) + 1)):
            problems_order.append(f"{request_id}: step numbers not 1..n")
        for s in rows:
            if s["approval_step_id"] != f"APR-{request_id}-{int(s['step_no']):02d}":
                problems_ids.append(s["approval_step_id"])
        # lifecycle of the steps: decided ... then PENDING ... then WAITING; REJECTED -> rest SKIPPED
        phase = "decided"
        last_date = parent["submitted_date"]
        for s in rows:
            st = s["status"]
            if (s["decided_date"] != "") != (st in ("APPROVED", "REJECTED")):
                problems_dates.append(f"{s['approval_step_id']}: decided_date vs status")
            if s["decided_date"]:
                if s["decided_date"] < last_date:
                    problems_dates.append(f"{s['approval_step_id']}: decided before previous step")
                last_date = s["decided_date"]
            if st in ("APPROVED", "SKIPPED") and phase == "decided":
                continue
            if st == "REJECTED" and phase == "decided":
                phase = "rejected"
            elif st == "SKIPPED" and phase == "rejected":
                continue
            elif st == "PENDING" and phase == "decided":
                phase = "waiting"
            elif st == "WAITING" and phase == "waiting":
                continue
            elif st == "SKIPPED" and phase == "waiting":
                continue            # same-approver skip
            else:
                problems_status.append(f"{request_id}: step {s['step_no']} is {st} in phase {phase}")
        # the request status must agree with its steps
        statuses = [s["status"] for s in rows]
        if parent["status"] in ("APPROVED", "REIMBURSED") and any(x in ("REJECTED", "PENDING", "WAITING") for x in statuses):
            problems_status.append(f"{request_id}: approved but steps are {statuses}")
        if parent["status"] == "REJECTED" and statuses.count("REJECTED") != 1:
            problems_status.append(f"{request_id}: rejected but steps are {statuses}")
        if parent["status"] == "PENDING_APPROVAL" and statuses.count("PENDING") != 1:
            problems_status.append(f"{request_id}: pending but steps are {statuses}")
    # requests without steps must be screening rejections
    screening = {"NO_WORKING_DAYS", "OVERLAPPING_LEAVE", "INSUFFICIENT_BALANCE", "EXCEEDS_MAX_CONSECUTIVE",
                 "MISSING_COST_CENTER", "EXPENSE_OUTSIDE_EMPLOYMENT", "MISSING_RECEIPT", "DUPLICATE_RECEIPT_HASH"}
    for request_id, parent in list(leave.items()) + list(claim.items()):
        if request_id not in steps and not (parent["status"] == "REJECTED" and parent["final_reason_code"] in screening):
            problems_status.append(f"{request_id}: no approval steps and not a screening rejection")
        if parent["status"] == "PENDING_APPROVAL" and parent["final_decision_date"]:
            problems_dates.append(f"{request_id}: pending with a decision date")
        if parent["status"] != "PENDING_APPROVAL" and not parent["final_decision_date"]:
            problems_dates.append(f"{request_id}: decided without a decision date")
    report.check("approval_steps: numbering and id format", problems_order + problems_ids)
    report.check("approval_steps: lifecycle (decided -> pending -> waiting, rejection skips the rest)", problems_status)
    report.check("approval_steps: decision dates", problems_dates)


def reimbursement_checks(data, report):
    claim = {c["expense_claim_id"]: c for c in data["expense_claims"]}
    by_claim = {}
    for r in data["reimbursements"]:
        by_claim.setdefault(r["expense_claim_id"], []).append(r)
    problems = []
    for r in data["reimbursements"]:
        c = claim[r["expense_claim_id"]]
        if c["status"] not in ("APPROVED", "REIMBURSED"):
            problems.append(f"{r['reimbursement_id']}: claim {c['expense_claim_id']} is {c['status']}")
        if r["employee_id"] != c["employee_id"]:
            problems.append(f"{r['reimbursement_id']}: employee differs from claim")
        if abs(float(r["amount"]) - float(c["total_amount"])) > 0.001:
            problems.append(f"{r['reimbursement_id']}: amount differs from claim total")
        if r["approved_date"] != c["final_decision_date"] or r["payment_date"] < r["approved_date"]:
            problems.append(f"{r['reimbursement_id']}: date problem")
        expected = "PAID" if r["payment_date"] <= C.AS_OF_DATE.isoformat() else "SCHEDULED"
        if r["status"] != expected:
            problems.append(f"{r['reimbursement_id']}: status {r['status']} expected {expected}")
    for c in claim.values():
        rows = by_claim.get(c["expense_claim_id"], [])
        if c["status"] in ("APPROVED", "REIMBURSED") and not rows:
            problems.append(f"{c['expense_claim_id']}: approved but never scheduled for payment")
        if c["status"] == "REIMBURSED" and not any(r["status"] == "PAID" for r in rows):
            problems.append(f"{c['expense_claim_id']}: REIMBURSED but nothing paid")
        if c["status"] == "APPROVED" and any(r["status"] == "PAID" for r in rows):
            problems.append(f"{c['expense_claim_id']}: APPROVED but already paid")
    report.check("reimbursements: only for approved claims; amounts, dates and status reconcile", problems)


ALLOWED_TRANSITIONS = {
    None: {"SUBMITTED"}, "SUBMITTED": {"PENDING_APPROVAL", "REJECTED"},
    "PENDING_APPROVAL": {"APPROVED", "REJECTED"}, "APPROVED": {"REIMBURSED"},
}


def event_checks(data, report):
    owners = {r["leave_request_id"]: r for r in data["leave_requests"]}
    owners.update({c["expense_claim_id"]: c for c in data["expense_claims"]})
    history = {}
    for e in data["status_events"]:
        history.setdefault(e["leave_request_id"] or e["expense_claim_id"], []).append(e)
    problems = []
    for request_id, owner in owners.items():
        events = sorted(history.get(request_id, []), key=lambda e: e["event_id"])
        previous, day = None, ""
        for e in events:
            if (e["from_status"] or None) != previous:
                problems.append(f"{request_id}: {e['event_id']} starts from {e['from_status']!r}, expected {previous!r}")
            if e["to_status"] not in ALLOWED_TRANSITIONS.get(previous, set()):
                problems.append(f"{request_id}: illegal transition {previous} -> {e['to_status']}")
            if e["event_date"] < day:
                problems.append(f"{request_id}: events out of date order")
            previous, day = e["to_status"], e["event_date"]
        if previous != owner["status"]:
            problems.append(f"{request_id}: last event {previous} but status {owner['status']}")
    ids = [int(e["event_id"][4:]) for e in data["status_events"]]
    if sorted(ids) != list(range(1, len(ids) + 1)):
        problems.append("event ids are not 1..n without gaps")
    report.check("status_events: legal transitions, history ends at the current status", problems)


def id_sequence_checks(data, report):
    problems = []
    for table, column in [("employees", "employee_id"), ("leave_requests", "leave_request_id"),
                          ("expense_claims", "expense_claim_id"), ("reimbursements", "reimbursement_id")]:
        numbers = sorted(int(r[column].split("-")[-1]) for r in data[table])
        if numbers != list(range(1, len(numbers) + 1)):
            problems.append(f"{table}: ids are not 1..n without gaps")
    report.check("ID counters are zero padded and gap free", problems)


def ground_truth_checks(data, report):
    ids = {"LEAVE_REQUEST": {r["leave_request_id"] for r in data["leave_requests"]},
           "EXPENSE_CLAIM": {r["expense_claim_id"] for r in data["expense_claims"]},
           "LEAVE_BALANCE": {r["leave_balance_id"] for r in data["leave_balances"]}}
    problems = [f"{g['ground_truth_id']}: {g['entity_id']} not found" for g in data["ground_truth"]
                if g["entity_id"] not in ids[g["entity_type"]]]
    pairs = [(g["entity_id"], g["issue_type"]) for g in data["ground_truth"]]
    if len(pairs) != len(set(pairs)):
        problems.append("the same (entity, issue) is labelled twice")
    report.check("ground_truth: every label points to a real record", problems)
    # no leakage: the input tables must not contain any ground truth column
    leaked = [t for t in S.INPUT_TABLES if {"issue_type", "ground_truth_id", "origin"} & set(S.column_names(t))]
    report.check("ground_truth: no label columns inside input tables", leaked)


def validate(data_dir=DATA_DIR):
    data = load(data_dir)
    report = Report()
    generic_checks(data, report)
    employee_checks(data, report)
    leave_checks(data, report)
    expense_checks(data, report)
    approval_checks(data, report)
    reimbursement_checks(data, report)
    event_checks(data, report)
    id_sequence_checks(data, report)
    ground_truth_checks(data, report)
    return data, report


def write_summary(report, data, path):
    lines = ["# Validation summary", "",
             "Produced by `python validate_data.py`. Structural checks only; business rules are in `audit_report.md`.", "",
             "| # | Check | Result |", "|---|---|---|"]
    for number, (name, problems) in enumerate(report.results, start=1):
        lines.append(f"| {number} | {name} | {'PASS' if not problems else 'FAIL (' + str(len(problems)) + ')'} |")
    lines += ["", f"**{len(report.results) - len(report.failed)} of {len(report.results)} checks passed.**", "",
              "## Row counts", ""]
    lines += [f"- {t}: {len(rows)}" for t, rows in data.items()]
    for name, problems in report.failed:
        lines += ["", f"## Problems: {name}"] + [f"- {p}" for p in problems[:15]]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else DATA_DIR
    data, report = validate(folder)
    for name, problems in report.results:
        print(("PASS  " if not problems else "FAIL  ") + name)
        for p in problems[:5]:
            print("        " + p)
    write_summary(report, data, os.path.join(ROOT, "docs", "validation_summary.md"))
    print(f"\n{len(report.results) - len(report.failed)}/{len(report.results)} checks passed")
    sys.exit(1 if report.failed else 0)
