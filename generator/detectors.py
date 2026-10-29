"""
detectors.py - finds CONTROL FAILURES in the stored data.

Each detector reads only the input tables (never ground_truth) and answers:
"did something get through approval that the rules say should not have?"
The seven detectors match the seven required edge cases.

Input: `data` = {table name: list of row dictionaries} (values may be text, as read from CSV).
Output: list of dictionaries (entity_type, entity_id, issue_type, detail).
"""
from datetime import date

from generator import config as C
from generator.rules import ranges_overlap


def d(text):
    return date.fromisoformat(str(text))


def finding(entity_type, entity_id, issue, detail):
    return {"entity_type": entity_type, "entity_id": entity_id, "issue_type": issue, "detail": detail}


def negative_leave_balance(data):
    """An APPROVED request asked for more days than were available when it was submitted."""
    found = []
    for r in data["leave_requests"]:
        if r["status"] == "APPROVED" and r["balance_at_submission"] != "":
            if float(r["business_days"]) > float(r["balance_at_submission"]):
                found.append(finding("LEAVE_REQUEST", r["leave_request_id"], "NEGATIVE_LEAVE_BALANCE",
                                     f"approved {r['business_days']} days with only {r['balance_at_submission']} available"))
    return found


def overlapping_approved_leave(data):
    """Two APPROVED requests of one employee overlap. The later request is flagged."""
    found, by_employee = [], {}
    for r in sorted(data["leave_requests"], key=lambda x: x["leave_request_id"]):
        if r["status"] != "APPROVED":
            continue
        for other in by_employee.get(r["employee_id"], []):
            if ranges_overlap(d(r["start_date"]), d(r["end_date"]), d(other["start_date"]), d(other["end_date"])):
                found.append(finding("LEAVE_REQUEST", r["leave_request_id"], "OVERLAPPING_APPROVED_LEAVE",
                                     "overlaps approved " + other["leave_request_id"]))
                break
        by_employee.setdefault(r["employee_id"], []).append(r)
    return found


def expense_outside_employment(data):
    """A claim that is not rejected has a line dated before hire or after termination."""
    emp = {e["employee_id"]: e for e in data["employees"]}
    claims = {c["expense_claim_id"]: c for c in data["expense_claims"]}
    found, flagged = [], set()
    for line in data["expense_lines"]:
        claim = claims[line["expense_claim_id"]]
        if claim["status"] == "REJECTED" or claim["expense_claim_id"] in flagged:
            continue
        e = emp[claim["employee_id"]]
        day = d(line["expense_date"])
        before = day < d(e["hire_date"])
        after = e["termination_date"] != "" and day > d(e["termination_date"])
        if before or after:
            flagged.add(claim["expense_claim_id"])
            found.append(finding("EXPENSE_CLAIM", claim["expense_claim_id"], "EXPENSE_OUTSIDE_EMPLOYMENT",
                                 f"line dated {line['expense_date']} is outside employment"))
    return found


def missing_cost_center(data):
    return [finding("EXPENSE_CLAIM", c["expense_claim_id"], "MISSING_COST_CENTER", "claim has no cost centre")
            for c in data["expense_claims"] if c["cost_center_id"] == "" and c["status"] != "REJECTED"]


def split_claims(data):
    """
    Same employee, same purpose, claims submitted within 7 days of each other,
    each total between 400 and 500 (just under the 500 threshold) and together above 500.
    Status does not matter: a rejected attempt is still an attempt.
    """
    found, groups = [], {}
    for c in data["expense_claims"]:
        total = float(c["total_amount"])
        if 400 <= total <= 500:
            groups.setdefault((c["employee_id"], c["purpose"]), []).append(c)
    for (employee, purpose), claims in groups.items():
        claims.sort(key=lambda c: c["submitted_date"])
        cluster = [claims[0]]
        for c in claims[1:] + [None]:
            if c is not None and (d(c["submitted_date"]) - d(cluster[-1]["submitted_date"])).days <= 7:
                cluster.append(c)
                continue
            if len(cluster) >= 2 and sum(float(x["total_amount"]) for x in cluster) > 500:
                for x in cluster:
                    found.append(finding("EXPENSE_CLAIM", x["expense_claim_id"], "SPLIT_CLAIM_EVASION",
                                         f"{len(cluster)} claims just under 500 within 7 days by {employee}"))
            cluster = [c] if c is not None else []
    return found


def self_approval(data):
    """An approval step whose approver is the person who made the request."""
    owner = {}
    for r in data["leave_requests"]:
        owner[r["leave_request_id"]] = ("LEAVE_REQUEST", r["employee_id"])
    for c in data["expense_claims"]:
        owner[c["expense_claim_id"]] = ("EXPENSE_CLAIM", c["employee_id"])
    found, seen = [], set()
    for s in data["approval_steps"]:
        request_id = s["leave_request_id"] or s["expense_claim_id"]
        kind, requester = owner[request_id]
        if s["approver_id"] == requester and request_id not in seen:
            seen.add(request_id)
            found.append(finding(kind, request_id, "SELF_APPROVAL", f"step {s['step_no']} approved by the requester"))
    return found


def duplicate_reimbursement(data):
    counts = {}
    for r in data["reimbursements"]:
        counts.setdefault(r["expense_claim_id"], []).append(r["reimbursement_id"])
    return [finding("EXPENSE_CLAIM", claim, "DUPLICATE_REIMBURSEMENT", "paid more than once: " + ", ".join(ids))
            for claim, ids in sorted(counts.items()) if len(ids) > 1]


DETECTORS = [negative_leave_balance, overlapping_approved_leave, expense_outside_employment,
             missing_cost_center, split_claims, self_approval, duplicate_reimbursement]


def run_all(data):
    """Runs every detector and numbers the findings DET-000001..."""
    findings = []
    for detector in DETECTORS:
        findings.extend(detector(data))
    findings.sort(key=lambda f: (f["entity_type"], f["entity_id"], f["issue_type"]))
    for number, f in enumerate(findings, start=1):
        f["detection_id"] = f"DET-{number:06d}"
    return findings
