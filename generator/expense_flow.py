"""
expense_flow.py - the EXPENSE workflow.

  make_raw_claims()      creates claims + lines (receipts, dates, amounts) - no decisions yet
  make_duplicate_receipts(), inject_data_defects()   plant the labelled edge cases
  decide_claims()        walks the claims in ID order:
                         totals -> screening -> budget -> routing -> approval steps -> events
"""
import hashlib
import random
from datetime import date, timedelta

from generator import config as C
from generator import rules
from generator.flow_common import build_plans, status_events, step_rows
from generator.helpers import line_id, random_date
from generator.masters import can_raise_requests


def claim_window(emp):
    """Dates on which this employee can have submitted a claim."""
    first = max(emp["hire_date"] + timedelta(days=3), date(C.YEAR, 1, 12))
    last = min(C.AS_OF_DATE, emp["termination_date"] or C.AS_OF_DATE)
    return first, last


def receipt_hash(key, line_no):
    """Fingerprint of a receipt file. Deterministic: same seed -> same hash."""
    return hashlib.sha256(f"{C.SEED}-{key}-{line_no}".encode()).hexdigest()[:16]


def make_line(rng, category, amount, submitted, emp, policy, key, line_no, merchant=None):
    """One expense line. Receipt rules follow the category policy."""
    expense_date = max(submitted - timedelta(days=rng.randint(0, 25)), emp["hire_date"])
    needs_receipt = amount > float(policy["receipt_required_above"])
    if needs_receipt:
        provided = rng.random() > C.P_MISSING_RECEIPT
    else:
        provided = rng.random() < C.P_OPTIONAL_RECEIPT
    return {
        "category": category, "line_no": line_no, "expense_policy_id": policy["expense_policy_id"],
        "expense_date": expense_date,
        "merchant": merchant or f"{C.MERCHANT_PREFIX[category]} {rng.randint(1, 99)}",
        "amount": amount, "receipt_provided": provided,
        "receipt_hash": receipt_hash(key, line_no) if provided else None,
    }


def normal_amount(rng, category, policy):
    """A normal line stays within its limit; 4% of lines are made a breach on purpose."""
    limit = float(policy["max_line_amount"])
    if rng.random() < C.P_POLICY_BREACH_LINE:
        return round(limit * rng.uniform(*C.BREACH_FACTOR_RANGE), 2)
    low, mode = C.AMOUNT_RANGES[category]
    return min(round(rng.triangular(low, limit, mode), 2), limit)


def new_raw(emp, submitted, purpose, key, tag=None):
    return {"employee_id": emp["employee_id"], "submitted": submitted, "purpose": purpose,
            "cost_center_id": emp["cost_center_id"], "country": emp["country"],
            "lines": [], "tag": tag, "override": False, "key": key}


def pick_employee_with_window(rng, people, latest=None):
    """Random eligible employee whose claim window is not empty (and ends by 'latest' if given)."""
    while True:
        emp = rng.choice(people)
        first, last = claim_window(emp)
        if latest:
            last = min(last, latest)
        if first <= last:
            return emp, first, last


def make_raw_claims(rng, employees, policies, how_many, boundary_specs, split_groups):
    """
    Baseline claims first, then the planned special claims:
      * boundary claims  - totals exactly on 500 / 2000 / 10000
      * split claims     - 3 claims just under 500 by the same person (threshold evasion)
    """
    policy_by_cat = {p["category"]: p for p in policies}
    people = [e for e in employees if can_raise_requests(e)]
    categories = list(C.CATEGORY_WEIGHTS)
    weights = list(C.CATEGORY_WEIGHTS.values())
    raws = []

    # --- boundary claims (valid, but sitting exactly on a threshold)
    for total, parts in boundary_specs:
        emp, first, last = pick_employee_with_window(rng, people)
        raw = new_raw(emp, random_date(rng, first, last), "Project purchase", len(raws), tag="BOUNDARY")
        raw["boundary_total"] = total
        for number, (category, amount) in enumerate(parts, start=1):
            line = make_line(rng, category, amount, raw["submitted"], emp, policy_by_cat[category], raw["key"], number)
            line["receipt_provided"], line["receipt_hash"] = True, receipt_hash(raw["key"], number)
            raw["lines"].append(line)
        raws.append(raw)

    # --- split claims: 3 claims, each 440-499 USD, 1-3 days apart, same purpose and merchant
    latest = C.AS_OF_DATE - timedelta(days=40)
    for group in range(1, split_groups + 1):
        emp, first, last = pick_employee_with_window(rng, people, latest)
        base = random_date(rng, first, last)
        merchant = f"Tech Store {rng.randint(100, 999)}"
        for part in range(C.SPLIT_GROUP_SIZE):
            raw = new_raw(emp, base + timedelta(days=part * rng.randint(1, 2)), "Project purchase",
                          len(raws), tag=f"SPLIT-{group:02d}")
            total = round(rng.uniform(440, 499), 2)
            first_amount = round(rng.uniform(220, 299), 2)
            for number, amount in enumerate([first_amount, round(total - first_amount, 2)], start=1):
                line = make_line(rng, "SUPPLIES", amount, raw["submitted"], emp, policy_by_cat["SUPPLIES"],
                                 raw["key"], number, merchant)
                line["receipt_provided"], line["receipt_hash"] = True, receipt_hash(raw["key"], number)
                raw["lines"].append(line)
            raws.append(raw)

    # --- baseline claims
    while len(raws) < how_many:
        emp, first, last = pick_employee_with_window(rng, people)
        raw = new_raw(emp, random_date(rng, first, last), rng.choice(C.CLAIM_PURPOSES), len(raws))
        bulk = rng.random() < C.BULK_CLAIM_SHARE
        count = rng.randint(4, 10) if bulk else rng.choices(range(1, 11), C.LINES_PER_CLAIM_WEIGHTS)[0]
        for number in range(1, count + 1):
            category = rng.choice(C.BULK_CATEGORIES) if bulk else rng.choices(categories, weights)[0]
            policy = policy_by_cat[category]
            amount = normal_amount(rng, category, policy)
            raw["lines"].append(make_line(rng, category, amount, raw["submitted"], emp, policy, raw["key"], number))
        raws.append(raw)
    return raws


def make_duplicate_receipts(rng, raws, pairs):
    """Copy a receipt hash from one claim to another claim of the SAME employee (baseline duplicate)."""
    by_employee = {}
    for raw in raws:
        if raw["tag"] is None and any(l["receipt_hash"] for l in raw["lines"]):
            by_employee.setdefault(raw["employee_id"], []).append(raw)
    candidates = [claims for claims in by_employee.values() if len(claims) >= 2]
    rng.shuffle(candidates)
    for claims in candidates[:pairs]:
        original, copy = rng.sample(claims, 2)
        source = next(l for l in original["lines"] if l["receipt_hash"])
        target = next(l for l in copy["lines"] if l["receipt_hash"])
        target["receipt_hash"] = source["receipt_hash"]
        original["tag"] = copy["tag"] = "DUP"


def inject_data_defects(rng, raws, employees, counts, policies):
    """
    Plants 'expense date outside employment' and 'missing cost centre' on clean, old claims.
    The claim is later approved by override, so the control failure is visible in the data.
    """
    emp_by_id = {e["employee_id"]: e for e in employees}
    policy_by_id = {p["expense_policy_id"]: p for p in policies}
    cutoff = C.AS_OF_DATE - timedelta(days=25)     # old enough to be fully approved by the as-of date

    def clean(raw):
        return (raw["tag"] is None and raw["cost_center_id"] and raw["submitted"] <= cutoff
                and rules.worst_line_status(raw["lines"], policy_by_id) == "WITHIN"
                and not rules.has_missing_receipt(raw["lines"], policy_by_id))

    pool = [r for r in raws if clean(r)]
    rng.shuffle(pool)

    new_hires = [r for r in pool if emp_by_id[r["employee_id"]]["hire_date"] > date(C.YEAR, 1, 20)]
    leavers = [r for r in pool if emp_by_id[r["employee_id"]]["termination_date"]]
    n_outside = counts["EXPENSE_OUTSIDE_EMPLOYMENT"]
    n_leavers = min(n_outside // 3, len(leavers))
    for raw in leavers[:n_leavers]:                       # spent after the person left
        left_on = emp_by_id[raw["employee_id"]]["termination_date"]
        raw["submitted"] = left_on + timedelta(days=rng.randint(2, 8))
        raw["lines"][0]["expense_date"] = left_on + timedelta(days=1)
        raw["tag"], raw["override"] = "OUTSIDE", True
    for raw in [r for r in new_hires if r["tag"] is None][:n_outside - n_leavers]:   # spent before joining
        joined = emp_by_id[raw["employee_id"]]["hire_date"]
        raw["lines"][0]["expense_date"] = joined - timedelta(days=rng.randint(3, 30))
        raw["tag"], raw["override"] = "OUTSIDE", True

    rest = [r for r in pool if r["tag"] is None]
    for raw in rest[:counts["MISSING_COST_CENTER"]]:
        raw["cost_center_id"] = None
        raw["tag"], raw["override"] = "NOCC", True


def sort_and_number(raws, make_id):
    raws.sort(key=lambda r: (r["submitted"], r["employee_id"], r["key"]))
    for number, raw in enumerate(raws, start=1):
        raw["id"] = make_id(number)


def decide_claims(raws, ctx):
    """Applies the rules to every claim in ID order. Returns one result dictionary per claim."""
    committed = {}          # cost centre -> USD of earlier APPROVED claims (budget used so far)
    seen_hashes = set()     # receipt hashes of earlier claims
    results = []
    for raw in raws:
        emp = ctx["emp"][raw["employee_id"]]
        lines = raw["lines"]
        total = round(sum(l["amount"] for l in lines), 2)
        worst = rules.worst_line_status(lines, ctx["policy"])
        missing = rules.has_missing_receipt(lines, ctx["policy"])

        hashes = [l["receipt_hash"] for l in lines if l["receipt_hash"]]
        duplicate = len(set(hashes)) < len(hashes) or any(h in seen_hashes for h in hashes)
        seen_hashes.update(hashes)

        outside = any(l["expense_date"] < emp["hire_date"] or
                      (emp["termination_date"] and l["expense_date"] > emp["termination_date"]) for l in lines)

        cc = raw["cost_center_id"]
        exceeded, overshoot = rules.budget_position(committed.get(cc, 0), total, ctx["budget"].get(cc))
        failed = rules.claim_failed_checks(bool(cc), outside, missing, duplicate)
        overridden = raw["override"]
        screening_code = failed[0] if (failed and not overridden) else None

        facts = {"total": total, "categories": {l["category"] for l in lines}, "country": raw["country"],
                 "policy_breach": worst != "WITHIN", "budget_exceeded": exceeded,
                 "worst_line": worst, "overshoot": overshoot}
        plans = []
        if screening_code:
            status, final_date, final_code = "REJECTED", raw["submitted"], screening_code
        else:
            if overridden:
                decide = lambda role: ("APPROVED", "APPROVED_WITHIN_POLICY", "Approved (control override)")
            else:
                decide = lambda role: rules.expense_step_decision(role, facts)
            plans = build_plans("EXPENSE", facts, ctx, emp, raw["submitted"], decide)
            timing = random.Random(f"{ctx['seed']}-{raw['id']}")
            status, final_date = rules.walk_steps(plans, raw["submitted"], timing, C.AS_OF_DATE)
            if status == "APPROVED":
                codes = [p["code"] for p in plans if p["status"] == "APPROVED"]
                final_code = "APPROVED_BY_OVERRIDE" if overridden else rules.claim_final_code(codes)
            elif status == "REJECTED":
                final_code = [p["code"] for p in plans if p["status"] == "REJECTED"][0]
            else:
                final_code = "AWAITING_APPROVAL"

        if status == "APPROVED" and cc:
            committed[cc] = committed.get(cc, 0) + total

        line_rows = []
        for l in lines:
            line_rows.append({
                "expense_line_id": line_id(raw["id"], l["line_no"]), "expense_claim_id": raw["id"],
                "line_no": l["line_no"], "expense_policy_id": l["expense_policy_id"],
                "expense_date": l["expense_date"], "merchant": l["merchant"], "amount": l["amount"],
                "receipt_provided": l["receipt_provided"],
                "receipt_file_name": f"{raw['id']}_L{l['line_no']:02d}.pdf" if l["receipt_provided"] else None,
                "receipt_hash": l["receipt_hash"],
            })
        row = {
            "expense_claim_id": raw["id"], "employee_id": emp["employee_id"], "cost_center_id": cc,
            "employee_country": raw["country"], "submitted_date": raw["submitted"], "purpose": raw["purpose"],
            "currency": "USD", "total_amount": total, "line_count": len(lines),
            "has_policy_breach": worst != "WITHIN", "budget_exceeded": exceeded,
            "status": status, "final_reason_code": final_code, "final_decision_date": final_date,
        }
        note = "Screening failed: " + ", ".join(failed) if failed else ""
        results.append({
            "row": row, "lines": line_rows, "plans": plans, "failed": failed, "worst": worst,
            "overshoot": overshoot, "tag": raw["tag"], "overridden": overridden,
            "steps": step_rows("expense", raw["id"], plans),
            "events": status_events("expense", raw["id"], emp["employee_id"], raw["submitted"], plans,
                                    status, final_date, final_code, screening_code, note),
        })
    return results
