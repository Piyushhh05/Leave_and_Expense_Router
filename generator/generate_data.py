"""
generate_data.py - runs the whole data generation, in the order the problem statement asks.

    python -m generator.generate_data                  (default: 400 employees, seed 20261022)
    python -m generator.generate_data --scale 0.25     (smaller "starter" dataset, same code)

Order:  masters -> leave requests -> expense claims -> injected edge cases ->
        derived tables (balances, reimbursements, events) -> ground truth -> files.
"""
import argparse
import json
import os
import random
import shutil
from datetime import timedelta

from generator import config as C
from generator import detectors, expense_flow, leave_flow, masters, rules, schema_spec
from generator.helpers import (balance_id, claim_id, count_days, event_id, file_sha256, fmt,
                               holiday_dates, leave_id, read_csv, reimbursement_id, write_csv, write_seed_sql)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(os.path.dirname(HERE), "data")


# ---------------------------------------------------------------------------
# Choosing which baseline requests become injected leave anomalies
# ---------------------------------------------------------------------------
def choose_leave_overrides(rng, first_pass, ctx, counts):
    """
    Looks at the first pass and picks requests that were rejected for EXACTLY ONE reason.
    A person will 'approve anyway' in the second pass. One request per employee, so the
    override cannot disturb another override.
    Returns {request id: injected issue type}.
    """
    cutoff = C.AS_OF_DATE - timedelta(days=12)          # old enough to be fully approved
    status = {r["row"]["leave_request_id"]: r["row"]["status"] for r in first_pass}
    held_final = {}
    for r in first_pass:
        row = r["row"]
        if row["status"] != "REJECTED" and row["balance_at_submission"] is not None:
            key = (row["employee_id"], row["leave_policy_id"])
            held_final[key] = held_final.get(key, 0) + row["business_days"]

    def final_balance_after(r):
        row = r["row"]
        emp, policy = ctx["emp"][row["employee_id"]], ctx["policy"][row["leave_policy_id"]]
        key = (row["employee_id"], row["leave_policy_id"])
        months = rules.months_accrued(emp["hire_date"], emp["termination_date"], C.AS_OF_DATE)
        accrued = rules.accrued_days(policy["annual_days"], policy["accrual_per_month"], months)
        return ctx["openings"][key] + accrued - held_final.get(key, 0) - row["business_days"]

    negative = [r for r in first_pass if r["failed"] == ["INSUFFICIENT_BALANCE"]
                and r["row"]["submitted_date"] <= cutoff]
    # prefer cases where the balance is still negative today
    negative.sort(key=lambda r: final_balance_after(r) >= 0)
    overlap = [r for r in first_pass if r["failed"] == ["OVERLAPPING_LEAVE"]
               and r["row"]["submitted_date"] <= cutoff
               and any(status[c] == "APPROVED" for c in r["clashes"])]
    rng.shuffle(overlap)

    chosen, used_employees = {}, set()
    for issue, pool, how_many in [("NEGATIVE_LEAVE_BALANCE", negative, counts["NEGATIVE_LEAVE_BALANCE"]),
                                  ("OVERLAPPING_APPROVED_LEAVE", overlap, counts["OVERLAPPING_APPROVED_LEAVE"])]:
        taken = 0
        for r in pool:
            employee = r["row"]["employee_id"]
            if taken == how_many:
                break
            if employee in used_employees:
                continue
            used_employees.add(employee)
            chosen[r["row"]["leave_request_id"]] = issue
            taken += 1
    return chosen


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------
def build_ground_truth(leave_results, claim_results, leave_overrides, self_approved, dup_paid, ctx):
    labels = []

    def add(entity_type, entity_id, issue, origin, expected, group=None, notes=None):
        labels.append({"entity_type": entity_type, "entity_id": entity_id, "issue_type": issue,
                       "origin": origin, "expected_decision": expected, "group_id": group, "notes": notes})

    overlap_group = 0
    for res in leave_results:
        row = res["row"]
        rid = row["leave_request_id"]
        if res["overridden"]:
            issue = leave_overrides[rid]
            group = None
            note = f"approved with {row['business_days']} days, available {row['balance_at_submission']}"
            if issue == "OVERLAPPING_APPROVED_LEAVE":
                overlap_group += 1
                group, note = f"OVERLAP-{overlap_group:02d}", "overlaps " + ", ".join(res["clashes"])
            expected = "REJECT (INSUFFICIENT_BALANCE)" if issue == "NEGATIVE_LEAVE_BALANCE" else "REJECT (OVERLAPPING_LEAVE)"
            add("LEAVE_REQUEST", rid, issue, "INJECTED", expected, group, note)
        else:
            for check in res["failed"]:
                add("LEAVE_REQUEST", rid, check, "BASELINE_RULE", "REJECT",
                    notes=f"business days {row['business_days']}, available {row['balance_at_submission']}")
        country = ctx["emp"][row["employee_id"]]["country"]
        if rules.touches_weekend_or_holiday(row["start_date"], row["end_date"], ctx["holidays"][country]):
            add("LEAVE_REQUEST", rid, "WEEKEND_HOLIDAY_SPAN", "BASELINE_RULE", "COUNT_BUSINESS_DAYS_ONLY",
                notes=f"{row['calendar_days']} calendar days, {row['business_days']} business days")
        if len(res["plans"]) >= 3:
            add("LEAVE_REQUEST", rid, "MULTI_LEVEL_APPROVAL", "BASELINE_RULE", f"ROUTE_{len(res['plans'])}_STEPS",
                notes=">".join(p["role"] for p in res["plans"]))

    for res in claim_results:
        row = res["row"]
        cid = row["expense_claim_id"]
        tag = res["tag"] or ""
        if res["overridden"]:
            issue = "EXPENSE_OUTSIDE_EMPLOYMENT" if tag == "OUTSIDE" else "MISSING_COST_CENTER"
            add("EXPENSE_CLAIM", cid, issue, "INJECTED", "REJECT")
        else:
            for check in res["failed"]:
                add("EXPENSE_CLAIM", cid, check, "BASELINE_RULE", "REJECT")
        if tag.startswith("SPLIT"):
            add("EXPENSE_CLAIM", cid, "SPLIT_CLAIM_EVASION", "INJECTED", "ROUTE_AS_COMBINED_CLAIM", tag,
                f"total {row['total_amount']} is just under the {C.EXPENSE_SKIP_LEVEL_ABOVE} USD threshold")
        if res["worst"] != "WITHIN":
            add("EXPENSE_CLAIM", cid, "POLICY_LIMIT_BREACH", "BASELINE_RULE",
                "APPROVE_AS_EXCEPTION" if res["worst"] == "TOLERATED" else "REJECT", notes=res["worst"])
        if row["budget_exceeded"]:
            add("EXPENSE_CLAIM", cid, "BUDGET_EXCEEDED", "BASELINE_RULE",
                "APPROVE_AS_EXCEPTION" if res["overshoot"] <= C.BUDGET_OVERSHOOT_LIMIT else "REJECT",
                notes=f"overshoot {res['overshoot']:.1%}")
        if len(res["plans"]) >= 3:
            add("EXPENSE_CLAIM", cid, "MULTI_LEVEL_APPROVAL", "BASELINE_RULE", f"ROUTE_{len(res['plans'])}_STEPS",
                notes=">".join(p["role"] for p in res["plans"]))
        if tag == "BOUNDARY":
            add("EXPENSE_CLAIM", cid, "BOUNDARY_AMOUNT", "BASELINE_RULE", "AMOUNT_RULE_NOT_TRIGGERED",
                notes=f"total is exactly {row['total_amount']}")

    for kind, request_id in self_approved:
        entity_type = "LEAVE_REQUEST" if kind == "leave" else "EXPENSE_CLAIM"
        add(entity_type, request_id, "SELF_APPROVAL", "INJECTED", "REASSIGN_TO_MANAGER",
            notes="step 1 approver is the requester")
    for claim in dup_paid:
        add("EXPENSE_CLAIM", claim, "DUPLICATE_REIMBURSEMENT", "INJECTED", "PAY_ONCE")

    labels.sort(key=lambda x: (x["entity_type"], x["entity_id"], x["issue_type"]))
    for number, label in enumerate(labels, start=1):
        label["ground_truth_id"] = f"GT-{number:06d}"
    return labels


# ---------------------------------------------------------------------------
# The main build
# ---------------------------------------------------------------------------
def build(scale=1.0, seed=C.SEED):
    """Returns {table name: list of rows}. Pure function of (scale, seed)."""
    C.SEED = seed                                   # used inside receipt hashes
    rng = random.Random(seed)
    n_employees = round(C.DEFAULT_COUNTS["employees"] * scale)
    n_leave = round(C.DEFAULT_COUNTS["leave_requests"] * scale)
    n_claims = round(C.DEFAULT_COUNTS["expense_claims"] * scale)
    counts = {k: max(1, round(v * scale)) for k, v in C.INJECTED.items()}

    # ---- 1. master data
    holidays = masters.make_holidays()
    leave_policies = masters.make_leave_policies()
    expense_policies = masters.make_expense_policies()
    employees = masters.make_employees(rng, n_employees)
    cost_centers = masters.make_cost_centers(employees)
    openings = masters.make_openings(rng, employees, leave_policies)
    rule_rows = rules.approval_rule_rows()

    holiday_sets = {c: holiday_dates(holidays, c) for c in C.COUNTRIES}
    base_ctx = {"emp": {e["employee_id"]: e for e in employees}, "rules": rule_rows,
                "holders": masters.role_holders(employees), "seed": seed}
    leave_ctx = dict(base_ctx, policy={p["leave_policy_id"]: p for p in leave_policies},
                     holidays=holiday_sets, openings=openings)
    expense_ctx = dict(base_ctx, policy={p["expense_policy_id"]: p for p in expense_policies},
                       budget={c["cost_center_id"]: float(c["annual_budget"]) for c in cost_centers})

    # ---- 2. leave requests: first pass, choose overrides, final pass
    raw_leave = leave_flow.make_raw_leave(rng, employees, holidays, n_leave)
    leave_flow.sort_and_number(raw_leave, leave_id)
    first_pass = leave_flow.decide_leave(raw_leave, leave_ctx, set())
    leave_overrides = choose_leave_overrides(rng, first_pass, leave_ctx, counts)
    leave_results = leave_flow.decide_leave(raw_leave, leave_ctx, set(leave_overrides))

    # ---- 3. expense claims
    split_groups = counts["SPLIT_CLAIM_EVASION"]
    boundary = C.BOUNDARY_CLAIMS if n_claims >= 500 else C.BOUNDARY_CLAIMS[:3]
    raw_claims = expense_flow.make_raw_claims(rng, employees, expense_policies, n_claims, boundary, split_groups)
    expense_flow.make_duplicate_receipts(rng, raw_claims, round(C.P_DUPLICATE_RECEIPT * n_claims))
    expense_flow.inject_data_defects(rng, raw_claims, employees, counts, expense_policies)
    expense_flow.sort_and_number(raw_claims, claim_id)
    claim_results = expense_flow.decide_claims(raw_claims, expense_ctx)

    # ---- 4. self-approval: half on leave requests, half on claims (first step approver := requester)
    self_approved = []
    n_leave_self = counts["SELF_APPROVAL"] // 2
    n_claim_self = counts["SELF_APPROVAL"] - n_leave_self
    pools = [("leave", [r for r in leave_results if r["row"]["status"] == "APPROVED" and not r["overridden"]], n_leave_self),
             ("expense", [r for r in claim_results if r["row"]["status"] == "APPROVED" and not r["overridden"]
                          and r["tag"] is None], n_claim_self)]
    for kind, pool, how_many in pools:
        rng.shuffle(pool)
        for res in pool[:how_many]:
            res["steps"][0]["approver_id"] = res["row"]["employee_id"]
            key = "leave_request_id" if kind == "leave" else "expense_claim_id"
            self_approved.append((kind, res["row"][key]))

    # ---- 5. reimbursements: only for fully approved claims
    payments = []
    for res in claim_results:
        row = res["row"]
        if row["status"] != "APPROVED":
            continue
        pay_rng = random.Random(f"{seed}-pay-{row['expense_claim_id']}")
        payment_date = row["final_decision_date"] + timedelta(days=pay_rng.randint(*C.PAYMENT_DELAY_DAYS))
        payments.append({
            "expense_claim_id": row["expense_claim_id"], "employee_id": row["employee_id"],
            "amount": row["total_amount"], "currency": "USD",
            "payment_method": pay_rng.choice(["BANK_TRANSFER", "PAYROLL"]),
            "approved_date": row["final_decision_date"], "payment_date": payment_date,
            "status": "PAID" if payment_date <= C.AS_OF_DATE else "SCHEDULED", "copy": 0,
            "claim_result": res,
        })
        if payment_date <= C.AS_OF_DATE:
            row["status"] = "REIMBURSED"

    # injected: some paid claims are paid a second time
    self_ids = {request for _, request in self_approved}
    paid = [p for p in payments if p["status"] == "PAID" and p["payment_date"] <= C.AS_OF_DATE - timedelta(days=20)
            and p["claim_result"]["tag"] is None and p["expense_claim_id"] not in self_ids]
    rng.shuffle(paid)
    dup_paid = []
    for p in paid[:counts["DUPLICATE_REIMBURSEMENT"]]:
        second = dict(p, copy=1, payment_date=p["payment_date"] + timedelta(days=rng.randint(5, 15)))
        second["status"] = "PAID" if second["payment_date"] <= C.AS_OF_DATE else "SCHEDULED"
        payments.append(second)
        dup_paid.append(p["expense_claim_id"])
    payments.sort(key=lambda p: (p["payment_date"], p["expense_claim_id"], p["copy"]))
    reimbursements = []
    for number, p in enumerate(payments, start=1):
        p["reimbursement_id"] = reimbursement_id(number)
        reimbursements.append({k: p[k] for k in ["reimbursement_id", "expense_claim_id", "employee_id", "amount",
                                                 "currency", "payment_method", "approved_date", "payment_date", "status"]})

    # ---- 6. status events (append-only history)
    all_events = []
    for res in leave_results + claim_results:
        all_events.extend(res["events"])
    for p in payments:
        row = p["claim_result"]["row"]
        if row["status"] == "REIMBURSED" and p["copy"] == 0:
            all_events.append({"leave_request_id": None, "expense_claim_id": p["expense_claim_id"], "order": 4,
                               "from_status": "APPROVED", "to_status": "REIMBURSED", "event_date": p["payment_date"],
                               "actor_type": "SYSTEM", "actor_id": None, "reason_code": row["final_reason_code"],
                               "note": "Paid as " + p["reimbursement_id"]})
    for e in all_events:
        e.setdefault("leave_request_id", None)
        e.setdefault("expense_claim_id", None)
    all_events.sort(key=lambda e: (e["event_date"], e["leave_request_id"] or e["expense_claim_id"], e["order"]))
    for number, e in enumerate(all_events, start=1):
        e["event_id"] = event_id(number)

    # ---- 7. derived balances and the answer key
    balances = leave_flow.build_balances(employees, leave_policies, openings, leave_results, balance_id)
    ground_truth = build_ground_truth(leave_results, claim_results, leave_overrides, self_approved, dup_paid, leave_ctx)

    steps = [s for res in leave_results + claim_results for s in res["steps"]]
    tables = {
        "holidays": holidays, "cost_centers": cost_centers, "employees": employees,
        "leave_policies": leave_policies, "leave_balances": balances, "expense_policies": expense_policies,
        "approval_rules": rule_rows, "leave_requests": [r["row"] for r in leave_results],
        "expense_claims": [r["row"] for r in claim_results],
        "expense_lines": [l for r in claim_results for l in r["lines"]],
        "approval_steps": steps, "reimbursements": reimbursements, "status_events": all_events,
        "ground_truth": ground_truth,
    }
    return tables


# ---------------------------------------------------------------------------
# Writing files
# ---------------------------------------------------------------------------
def json_ready(row, columns):
    """Row -> dict with JSON friendly values (dates as text, empty as null)."""
    out = {}
    for c in columns:
        v = row.get(c)
        out[c] = None if v is None else (v if isinstance(v, (bool, int, float)) else fmt(v))
    return out


def write_all(tables, out_dir, scale, seed):
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(os.path.join(out_dir, "json"))

    # 1) CSV of everything we have so far, then run the detectors on what was written (text values)
    for name, rows in tables.items():
        write_csv(os.path.join(out_dir, name + ".csv"), schema_spec.column_names(name), rows)
    stored = {name: read_csv(os.path.join(out_dir, name + ".csv")) for name in schema_spec.INPUT_TABLES}
    tables["detected_exceptions"] = detectors.run_all(stored)
    write_csv(os.path.join(out_dir, "detected_exceptions.csv"),
              schema_spec.column_names("detected_exceptions"), tables["detected_exceptions"])

    # 2) JSON and SQL seed files
    for name, rows in tables.items():
        cols = schema_spec.column_names(name)
        with open(os.path.join(out_dir, "json", name + ".json"), "w", encoding="utf-8") as f:
            json.dump([json_ready(r, cols) for r in rows], f, indent=1)
    columns = {t: schema_spec.column_names(t) for t in schema_spec.LOAD_ORDER}
    write_seed_sql(os.path.join(out_dir, "seed_data.sql"), schema_spec.INPUT_TABLES, columns, tables)
    write_seed_sql(os.path.join(out_dir, "seed_evaluation.sql"), ["ground_truth", "detected_exceptions"], columns, tables)

    # 3) manifest: counts + checksums (used to prove reproducibility)
    manifest = {
        "seed": seed, "scale": scale, "as_of_date": C.AS_OF_DATE.isoformat(),
        "command": f"python -m generator.generate_data --scale {scale} --seed {seed}",
        "row_counts": {name: len(rows) for name, rows in tables.items()},
        "sha256": {name + ".csv": file_sha256(os.path.join(out_dir, name + ".csv")) for name in tables},
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Generate the synthetic leave & expense dataset")
    parser.add_argument("--scale", type=float, default=1.0, help="1.0 = 400 employees, 800 leave, 1000 claims")
    parser.add_argument("--seed", type=int, default=C.SEED)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()
    tables = build(args.scale, args.seed)
    manifest = write_all(tables, args.out, args.scale, args.seed)
    print(f"Wrote dataset to {args.out} (seed {args.seed}, scale {args.scale})")
    for name, count in manifest["row_counts"].items():
        print(f"  {name:22s} {count:6d} rows")


if __name__ == "__main__":
    main()
