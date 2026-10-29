"""
audit_rules.py - checks the BUSINESS RULES against the stored data and measures the results.

    python audit_rules.py          (reads ./data, writes docs/audit_report.md and docs/metrics.json)

It does three things:
  1. Re-runs the seven control-failure detectors and scores them against the injected ground truth.
  2. Re-computes every decision from the source rows (balance, screening, budget, routing path,
     approver) and compares with what is stored. A difference is only acceptable when the
     ground truth says it was planted on purpose.
  3. Computes business metrics (approval rates, cycle times, exceptions, money).
Exit code 1 if anything is unexplained.
"""
import json
import os
import sys
from collections import Counter
from datetime import date

from generator import config as C
from generator import detectors, rules
from generator.helpers import holiday_dates, ranges_overlap, read_csv

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
TABLES = ["employees", "cost_centers", "holidays", "leave_policies", "leave_balances", "leave_requests",
          "expense_policies", "expense_claims", "expense_lines", "approval_rules", "approval_steps",
          "reimbursements", "status_events", "ground_truth", "detected_exceptions"]


def d(text):
    return date.fromisoformat(text)


def load(data_dir):
    return {t: read_csv(os.path.join(data_dir, t + ".csv")) for t in TABLES}


def percent(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


# ---------------------------------------------------------------------------
# 1. Detector scoring
# ---------------------------------------------------------------------------
def score_detectors(data):
    """Precision / recall per injected issue type."""
    fresh = detectors.run_all(data)
    stored = {(x["entity_id"], x["issue_type"]) for x in data["detected_exceptions"]}
    same_as_file = stored == {(x["entity_id"], x["issue_type"]) for x in fresh}
    truth = {(g["entity_id"], g["issue_type"]) for g in data["ground_truth"] if g["origin"] == "INJECTED"}
    found = {(x["entity_id"], x["issue_type"]) for x in fresh}
    rows = []
    for issue in sorted({i for _, i in truth} | {i for _, i in found}):
        t = {e for e, i in truth if i == issue}
        f = {e for e, i in found if i == issue}
        tp, fp, fn = len(t & f), len(f - t), len(t - f)
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows.append({"issue": issue, "planted": len(t), "detected": len(f), "tp": tp, "fp": fp, "fn": fn,
                     "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)})
    return rows, same_as_file, truth


# ---------------------------------------------------------------------------
# 2. Re-computation of decisions from source rows
# ---------------------------------------------------------------------------
def recompute_leave(data):
    """Returns (recomputed labels, problems). Walks requests in ID order, like the generator did."""
    emp = {e["employee_id"]: e for e in data["employees"]}
    pol = {p["leave_policy_id"]: p for p in data["leave_policies"]}
    opening = {(b["employee_id"], b["leave_policy_id"]): float(b["opening_balance"]) for b in data["leave_balances"]}
    hol = {c: {d(h["holiday_date"]) for h in data["holidays"] if h["country"] == c} for c in C.COUNTRIES}
    steps = {}
    for s in data["approval_steps"]:
        if s["leave_request_id"]:
            steps.setdefault(s["leave_request_id"], []).append(s)

    held, live, labels, problems, stats = {}, {}, set(), [], Counter()
    for r in sorted(data["leave_requests"], key=lambda x: x["leave_request_id"]):
        rid, e, p = r["leave_request_id"], emp[r["employee_id"]], pol[r["leave_policy_id"]]
        start, end, bd = d(r["start_date"]), d(r["end_date"]), int(r["business_days"])
        deducts = p["deducts_balance"] == "1"
        key = (e["employee_id"], p["leave_policy_id"])
        available = None
        if deducts:
            term = d(e["termination_date"]) if e["termination_date"] else None
            months = rules.months_accrued(d(e["hire_date"]), term, d(r["submitted_date"]))
            available = opening[key] + rules.accrued_days(p["annual_days"], p["accrual_per_month"], months) - held.get(key, 0)
            if abs(available - float(r["balance_at_submission"])) > 0.001:
                problems.append(f"{rid}: balance_at_submission {r['balance_at_submission']} recomputed {available}")
        clashes = [x for (s, en, x) in live.get(e["employee_id"], []) if ranges_overlap(start, end, s, en)]
        failed = rules.leave_failed_checks(bd, deducts, available, int(p["max_consecutive_days"]), bool(clashes))

        stored_status = r["status"]
        if failed:
            if stored_status == "REJECTED":
                stats["screened_correctly"] += 1
                if r["final_reason_code"] != failed[0]:
                    problems.append(f"{rid}: rejected as {r['final_reason_code']}, rules say {failed[0]}")
            else:       # approved despite failing screening: only OK if planted
                mapped = {"INSUFFICIENT_BALANCE": "NEGATIVE_LEAVE_BALANCE", "OVERLAPPING_LEAVE": "OVERLAPPING_APPROVED_LEAVE"}
                stats["approved_despite_failure"] += 1
                for f in failed:
                    labels.add((rid, mapped.get(f, f)))
            if stored_status == "REJECTED":
                for f in failed:
                    labels.add((rid, f))
        elif stored_status == "REJECTED":
            problems.append(f"{rid}: rejected as {r['final_reason_code']} but passes every check")
        else:
            stats["passed_and_approved_or_pending"] += 1

        # routing path
        if not failed or stored_status != "REJECTED":
            facts = {"business_days": bd, "leave_type": p["leave_type"]}
            expected = [role for role, _ in rules.required_steps("LEAVE", facts, data["approval_rules"], d(r["submitted_date"]))]
            actual = [s["approver_role"] for s in sorted(steps.get(rid, []), key=lambda s: int(s["step_no"]))]
            stats["paths_checked"] += 1
            if expected != actual:
                problems.append(f"{rid}: path {actual} expected {expected}")
            if len(expected) >= 3:
                labels.add((rid, "MULTI_LEVEL_APPROVAL"))
        if rules.touches_weekend_or_holiday(start, end, hol[e["country"]]):
            labels.add((rid, "WEEKEND_HOLIDAY_SPAN"))

        if stored_status != "REJECTED":
            if deducts:
                held[key] = held.get(key, 0) + bd
            live.setdefault(e["employee_id"], []).append((start, end, rid))
    return labels, problems, stats


def recompute_claims(data):
    emp = {e["employee_id"]: e for e in data["employees"]}
    pol = {p["expense_policy_id"]: p for p in data["expense_policies"]}
    budget = {c["cost_center_id"]: float(c["annual_budget"]) for c in data["cost_centers"]}
    lines = {}
    for l in data["expense_lines"]:
        lines.setdefault(l["expense_claim_id"], []).append(l)
    cat_of = {p["expense_policy_id"]: p["category"] for p in data["expense_policies"]}
    steps = {}
    for s in data["approval_steps"]:
        if s["expense_claim_id"]:
            steps.setdefault(s["expense_claim_id"], []).append(s)
    thresholds = {C.EXPENSE_SKIP_LEVEL_ABOVE, C.EXPENSE_FINANCE_ABOVE, C.EXPENSE_CFO_ABOVE}

    committed, seen, labels, problems, stats = {}, set(), set(), [], Counter()
    for c in sorted(data["expense_claims"], key=lambda x: x["expense_claim_id"]):
        cid, e = c["expense_claim_id"], emp[c["employee_id"]]
        cl = lines[cid]
        total = round(sum(float(l["amount"]) for l in cl), 2)
        worst = rules.worst_line_status(cl, pol)
        missing = rules.has_missing_receipt(cl, pol)
        hashes = [l["receipt_hash"] for l in cl if l["receipt_hash"]]
        duplicate = len(set(hashes)) < len(hashes) or any(h in seen for h in hashes)
        seen.update(hashes)
        hire = d(e["hire_date"])
        term = d(e["termination_date"]) if e["termination_date"] else None
        outside = any(d(l["expense_date"]) < hire or (term and d(l["expense_date"]) > term) for l in cl)
        cc = c["cost_center_id"] or None
        exceeded, overshoot = rules.budget_position(committed.get(cc, 0), total, budget.get(cc))
        failed = rules.claim_failed_checks(bool(cc), outside, missing, duplicate)
        if exceeded != (c["budget_exceeded"] == "1"):
            problems.append(f"{cid}: budget_exceeded flag {c['budget_exceeded']} recomputed {exceeded}")

        stored = c["status"]
        for f in failed:
            labels.add((cid, f))
        if failed:
            if stored == "REJECTED":
                stats["screened_correctly"] += 1
                if c["final_reason_code"] != failed[0]:
                    problems.append(f"{cid}: rejected as {c['final_reason_code']}, rules say {failed[0]}")
            else:
                stats["approved_despite_failure"] += 1
        elif stored == "REJECTED" and c["final_reason_code"] in ("MISSING_COST_CENTER", "EXPENSE_OUTSIDE_EMPLOYMENT",
                                                                   "MISSING_RECEIPT", "DUPLICATE_RECEIPT_HASH"):
            problems.append(f"{cid}: rejected as {c['final_reason_code']} but passes screening")

        facts = {"total": total, "categories": {cat_of[l["expense_policy_id"]] for l in cl}, "country": c["employee_country"],
                 "policy_breach": worst != "WITHIN", "budget_exceeded": exceeded, "worst_line": worst, "overshoot": overshoot}
        routed = not failed or stored != "REJECTED"
        if routed:
            expected = [r for r, _ in rules.required_steps("EXPENSE", facts, data["approval_rules"], d(c["submitted_date"]))]
            actual_rows = sorted(steps.get(cid, []), key=lambda s: int(s["step_no"]))
            actual = [s["approver_role"] for s in actual_rows]
            stats["paths_checked"] += 1
            if expected != actual:
                problems.append(f"{cid}: path {actual} expected {expected}")
            if len(expected) >= 3:
                labels.add((cid, "MULTI_LEVEL_APPROVAL"))
            # each decided step must carry the decision the rules give (planted overrides approve everything)
            if not failed:
                for s in actual_rows:
                    if s["status"] in ("APPROVED", "REJECTED"):
                        status, code, _ = rules.expense_step_decision(s["approver_role"], facts)
                        if (status, code) != (s["status"], s["decision_reason_code"]):
                            problems.append(f"{s['approval_step_id']}: stored {s['status']}/{s['decision_reason_code']} rules say {status}/{code}")
        if worst != "WITHIN":
            labels.add((cid, "POLICY_LIMIT_BREACH"))
        if exceeded:
            labels.add((cid, "BUDGET_EXCEEDED"))
        if total in thresholds:
            labels.add((cid, "BOUNDARY_AMOUNT"))
        if stored in ("APPROVED", "REIMBURSED") and cc:
            committed[cc] = committed.get(cc, 0) + total
    return labels, problems, stats


def check_approvers(data):
    """Each step's approver must be the person the hierarchy says, senior enough, and not the requester."""
    emp = {e["employee_id"]: e for e in data["employees"]}
    holders = {e["special_role"]: e["employee_id"] for e in data["employees"] if e["special_role"]}
    owner = {r["leave_request_id"]: r["employee_id"] for r in data["leave_requests"]}
    owner.update({c["expense_claim_id"]: c["employee_id"] for c in data["expense_claims"]})
    min_level = {r["approval_rule_id"]: int(r["min_approver_level"]) for r in data["approval_rules"]}
    problems = []
    for s in data["approval_steps"]:
        request_id = s["leave_request_id"] or s["expense_claim_id"]
        requester = emp[owner[request_id]]
        expected = rules.resolve_approver(s["approver_role"], requester, emp, holders)
        if s["approver_id"] != expected:
            problems.append((request_id, f"{s['approval_step_id']}: approver {s['approver_id']} expected {expected}"))
        if s["approver_id"] == requester["employee_id"]:
            problems.append((request_id, f"{s['approval_step_id']}: approved by the requester"))
        if int(emp[s["approver_id"]]["job_level"]) < min_level[s["approval_rule_id"]]:
            problems.append((request_id, f"{s['approval_step_id']}: approver level too low"))
    return problems


def check_reimbursement_eligibility(data):
    """A reimbursement needs an approved claim whose steps are all approved (or skipped as duplicates)."""
    claims = {c["expense_claim_id"]: c for c in data["expense_claims"]}
    bad_status = Counter()
    problems = []
    for r in data["reimbursements"]:
        c = claims[r["expense_claim_id"]]
        steps = [s for s in data["approval_steps"] if s["expense_claim_id"] == c["expense_claim_id"]]
        if c["status"] not in ("APPROVED", "REIMBURSED") or any(s["status"] not in ("APPROVED", "SKIPPED") for s in steps):
            problems.append(f"{r['reimbursement_id']}: claim {c['expense_claim_id']} is not fully approved")
    return problems


# ---------------------------------------------------------------------------
# 3. Metrics
# ---------------------------------------------------------------------------
def cycle_days(rows):
    days = [(d(r["final_decision_date"]) - d(r["submitted_date"])).days for r in rows
            if r["final_decision_date"] and r["status"] != "REJECTED"]
    return round(sum(days) / len(days), 2) if days else 0


def build_metrics(data, detector_rows):
    leave, claims = data["leave_requests"], data["expense_claims"]
    steps_by = {}
    for s in data["approval_steps"]:
        steps_by.setdefault(s["leave_request_id"] or s["expense_claim_id"], []).append(s)
    routed_claims = [c for c in claims if c["expense_claim_id"] in steps_by]
    routed_leave = [r for r in leave if r["leave_request_id"] in steps_by]

    def path_len(row, key):
        return len([s for s in steps_by[row[key]] if s["status"] != "SKIPPED" or s["decision_reason_code"] == "EARLIER_STEP_REJECTED"])

    money = lambda rows: round(sum(float(c["total_amount"]) for c in rows), 2)
    paid = [r for r in data["reimbursements"] if r["status"] == "PAID"]
    all_decided = [x for x in leave + claims if x["status"] != "PENDING_APPROVAL"]
    with_reason = [x for x in all_decided if x["final_reason_code"]]
    steps_with_reason = [s for s in data["approval_steps"] if s["routing_reason"]]
    return {
        "volumes": {"employees": len(data["employees"]), "leave_requests": len(leave), "expense_claims": len(claims),
                    "expense_lines": len(data["expense_lines"]), "approval_steps": len(data["approval_steps"]),
                    "reimbursements": len(data["reimbursements"])},
        "leave": {
            "status": dict(Counter(r["status"] for r in leave)),
            "reasons": dict(Counter(r["final_reason_code"] for r in leave)),
            "approval_rate_of_decided_pct": percent(sum(r["status"] == "APPROVED" for r in leave),
                                                     sum(r["status"] != "PENDING_APPROVAL" for r in leave)),
            "screening_rejection_pct": percent(sum(r["status"] == "REJECTED" for r in leave), len(leave)),
            "average_business_days": round(sum(int(r["business_days"]) for r in leave) / len(leave), 2),
            "average_days_to_approve": cycle_days(leave),
            "manager_only_pct_of_routed": percent(sum(len(steps_by[r["leave_request_id"]]) == 1 for r in routed_leave), len(routed_leave)),
        },
        "expense": {
            "status": dict(Counter(c["status"] for c in claims)),
            "reasons": dict(Counter(c["final_reason_code"] for c in claims)),
            "approval_rate_of_decided_pct": percent(sum(c["status"] in ("APPROVED", "REIMBURSED") for c in claims),
                                                     sum(c["status"] != "PENDING_APPROVAL" for c in claims)),
            "total_submitted_usd": money(claims),
            "total_approved_usd": money([c for c in claims if c["status"] in ("APPROVED", "REIMBURSED")]),
            "total_paid_usd": round(sum(float(r["amount"]) for r in paid), 2),
            "average_claim_usd": round(money(claims) / len(claims), 2),
            "average_days_to_approve": cycle_days(claims),
            "manager_only_pct_of_routed": percent(sum(len(steps_by[c["expense_claim_id"]]) == 1 for c in routed_claims), len(routed_claims)),
            "three_or_more_levels_pct_of_routed": percent(sum(len(steps_by[c["expense_claim_id"]]) >= 3 for c in routed_claims), len(routed_claims)),
            "policy_exceptions_approved": sum(c["final_reason_code"] == "APPROVED_POLICY_EXCEPTION" for c in claims),
            "budget_exceptions_approved": sum(c["final_reason_code"] == "APPROVED_BUDGET_EXCEPTION" for c in claims),
            "claims_over_budget_flag": sum(c["budget_exceeded"] == "1" for c in claims),
        },
        "auditability": {
            "decided_requests_with_reason_code_pct": percent(len(with_reason), len(all_decided)),
            "steps_with_routing_reason_pct": percent(len(steps_with_reason), len(data["approval_steps"])),
        },
        "control_detection": detector_rows,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def audit(data_dir=DATA_DIR):
    data = load(data_dir)
    detector_rows, same_file, injected = score_detectors(data)
    injected_entities = {e for e, _ in injected}

    leave_labels, leave_problems, leave_stats = recompute_leave(data)
    claim_labels, claim_problems, claim_stats = recompute_claims(data)
    approver_problems = check_approvers(data)
    reimb_problems = check_reimbursement_eligibility(data)

    # compare recomputed rule-derived labels with the ground truth (same issue types only)
    recomputed = leave_labels | claim_labels
    types = {i for _, i in recomputed} | {"NEGATIVE_LEAVE_BALANCE", "OVERLAPPING_APPROVED_LEAVE"}
    truth = {(g["entity_id"], g["issue_type"]) for g in data["ground_truth"] if g["issue_type"] in types}
    missing_from_truth = sorted(recomputed - truth)
    missing_from_recompute = sorted(truth - recomputed)

    # self approval and duplicate reimbursement are planted on purpose -> explained; everything else is not
    unexplained_approver = [m for r, m in approver_problems if (r, "SELF_APPROVAL") not in injected]
    explained_approver = [m for r, m in approver_problems if (r, "SELF_APPROVAL") in injected]
    dup_claims = {e for e, i in injected if i == "DUPLICATE_REIMBURSEMENT"}
    unexplained_reimb = [m for m in reimb_problems]
    claims_with_two = Counter(r["expense_claim_id"] for r in data["reimbursements"])
    unexplained_dup = [c for c, n in claims_with_two.items() if n > 1 and c not in dup_claims]

    def unexplained(problems):
        return [p for p in problems if p.split(":")[0] not in injected_entities]

    sections = [
        ("Leave decisions recomputed from source rows", unexplained(leave_problems)),
        ("Expense decisions recomputed from source rows", unexplained(claim_problems)),
        ("Approver is the right person, senior enough, and not the requester", unexplained_approver),
        ("Reimbursements only for fully approved claims", unexplained_reimb),
        ("No unplanned duplicate reimbursement", unexplained_dup),
        ("Recomputed rule labels match ground truth (labels the data should have)", [str(x) for x in missing_from_truth]),
        ("Ground-truth rule labels are reproduced by the rules (labels the rules should give)", [str(x) for x in missing_from_recompute]),
        ("detected_exceptions.csv equals a fresh detector run", [] if same_file else ["file differs"]),
        ("Every planted anomaly is detected (recall 100%)", [r["issue"] for r in detector_rows if r["recall"] < 1.0]),
        ("Detectors raise no false alarms (precision 100%)", [r["issue"] for r in detector_rows if r["precision"] < 1.0]),
    ]
    metrics = build_metrics(data, detector_rows)
    metrics["rule_recomputation"] = {
        "leave_screened_correctly": leave_stats["screened_correctly"],
        "leave_approved_despite_failed_screening": leave_stats["approved_despite_failure"],
        "leave_paths_checked": leave_stats["paths_checked"],
        "claim_screened_correctly": claim_stats["screened_correctly"],
        "claim_approved_despite_failed_screening": claim_stats["approved_despite_failure"],
        "claim_paths_checked": claim_stats["paths_checked"],
        "self_approval_requests_found_and_explained": len({r for r, _ in approver_problems if (r, "SELF_APPROVAL") in injected}),
    }
    return data, sections, metrics, detector_rows


def write_report(sections, metrics, detector_rows, path_md, path_json):
    out = ["# Rule audit and evaluation report", "",
           "Produced by `python audit_rules.py`. The decisions stored in the data are re-computed from the source rows "
           "with `generator/rules.py`; a difference is acceptable only when the ground truth says it was planted.", "",
           "## Acceptance checks", "", "| Check | Unexplained issues | Result |", "|---|---|---|"]
    for name, problems in sections:
        out.append(f"| {name} | {len(problems)} | {'PASS' if not problems else 'FAIL'} |")
    out += ["", "## Control-failure detection (planted anomalies vs detectors)", "",
            "| Issue | Planted | Detected | TP | FP | FN | Precision | Recall | F1 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in detector_rows:
        out.append(f"| {r['issue']} | {r['planted']} | {r['detected']} | {r['tp']} | {r['fp']} | {r['fn']} | "
                   f"{r['precision']} | {r['recall']} | {r['f1']} |")
    for label in ("leave", "expense", "auditability", "rule_recomputation"):
        out += ["", f"## Metrics: {label}", "", "| Metric | Value |", "|---|---|"]
        for key, value in metrics[label].items():
            out.append(f"| {key} | {value} |")
    for name, problems in sections:
        if problems:
            out += ["", f"## Unexplained: {name}"] + [f"- {p}" for p in problems[:15]]
    with open(path_md, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    with open(path_json, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=1)


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else DATA_DIR
    data, sections, metrics, detector_rows = audit(folder)
    write_report(sections, metrics, detector_rows,
                 os.path.join(ROOT, "docs", "audit_report.md"), os.path.join(ROOT, "docs", "metrics.json"))
    failed = 0
    for name, problems in sections:
        print(("PASS  " if not problems else "FAIL  ") + name)
        for p in problems[:5]:
            print("        " + p)
        failed += bool(problems)
    print(f"\n{len(sections) - failed}/{len(sections)} acceptance checks passed")
    sys.exit(1 if failed else 0)
