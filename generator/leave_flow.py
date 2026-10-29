"""
leave_flow.py - the LEAVE workflow.

  make_raw_leave()  creates requests (dates, type) - no decisions yet
  decide_leave()    walks the requests in ID order and applies the business rules:
                    business days -> balance -> screening -> routing -> approval steps -> events
"""
import random
from datetime import date, timedelta

from generator import config as C
from generator import rules
from generator.flow_common import build_plans, status_events, step_rows
from generator.helpers import count_days, next_weekday, random_date, ranges_overlap
from generator.masters import can_raise_requests


def make_raw_leave(rng, employees, holidays, how_many):
    """Random leave requests. Overlap and holiday cases are created on purpose at a fixed rate."""
    people = [e for e in employees if can_raise_requests(e)]
    raws, by_employee = [], {}
    year_start = C.LEAVE_EARLIEST_START
    latest_start = C.AS_OF_DATE + timedelta(days=25)     # people plan a few weeks ahead
    attempts = 0
    while len(raws) < how_many:
        attempts += 1
        assert attempts < how_many * 200, "could not generate enough leave requests"
        emp = rng.choice(people)
        leave_type = rng.choices(C.LEAVE_TYPES, C.LEAVE_TYPE_WEIGHTS)[0]
        lengths, weights = C.LEAVE_LENGTH_CHOICES[leave_type]
        length = rng.choices(lengths, weights)[0]                 # calendar days
        window_start = max(emp["hire_date"], year_start)
        window_end = min(emp["termination_date"] or date(C.YEAR, 12, 18), latest_start)
        if window_end - timedelta(days=length) < window_start:
            continue
        last_start = window_end - timedelta(days=length - 1)

        roll = rng.random()
        mine = by_employee.get(emp["employee_id"], [])
        country_holidays = [h["holiday_date"] for h in holidays if h["country"] == emp["country"]]
        if roll < C.P_HOLIDAY_LEAVE:
            options = [h for h in country_holidays
                       if window_start <= h - timedelta(days=length - 1) and h <= window_end]
            if not options:
                continue
            start = rng.choice(options) - timedelta(days=rng.randint(0, length - 1))
        elif roll < C.P_HOLIDAY_LEAVE + C.P_OVERLAP_LEAVE and mine:
            other = rng.choice(mine)
            start = random_date(rng, other["start"], other["end"])
        else:
            start = random_date(rng, window_start, last_start)
            if rng.random() < C.P_WEEKDAY_START:
                start = next_weekday(start)
        end = start + timedelta(days=length - 1)
        if start < window_start or end > window_end:
            continue

        lead = {"ANNUAL": (3, 30), "CASUAL": (1, 7), "UNPAID": (7, 30), "SICK": (0, 1)}[leave_type]
        submitted = start - timedelta(days=rng.randint(*lead))
        submitted = min(submitted, C.AS_OF_DATE - timedelta(days=rng.randint(0, 4)))
        submitted = max(submitted, emp["hire_date"], date(C.YEAR, 1, 1))
        policy_id = (C.ANNUAL_POLICY_BY_COUNTRY[emp["country"]] if leave_type == "ANNUAL"
                     else C.POLICY_BY_TYPE[leave_type])
        raw = {"employee_id": emp["employee_id"], "leave_type": leave_type, "policy_id": policy_id,
               "start": start, "end": end, "submitted": submitted,
               "reason": rng.choice(C.LEAVE_REASONS[leave_type])}
        raws.append(raw)
        by_employee.setdefault(emp["employee_id"], []).append(raw)
    return raws


def sort_and_number(raws, make_id):
    """Order by submission date, then hand out IDs. IDs never change afterwards."""
    raws.sort(key=lambda r: (r["submitted"], r["employee_id"], r["start"]))
    for number, raw in enumerate(raws, start=1):
        raw["id"] = make_id(number)


def decide_leave(raws, ctx, overrides):
    """
    Applies the rules to every request in ID order (older requests first).
    overrides = IDs that a person approved even though screening failed (injected anomalies).
    Returns one result dictionary per request.
    """
    held = {}      # (employee, policy) -> business days held by earlier non-rejected requests
    live = {}      # employee -> [(start, end, request id)] of earlier non-rejected requests
    results = []
    for raw in raws:
        emp = ctx["emp"][raw["employee_id"]]
        policy = ctx["policy"][raw["policy_id"]]
        calendar_days, business_days = count_days(raw["start"], raw["end"], ctx["holidays"][emp["country"]])
        deducts = policy["deducts_balance"]
        key = (emp["employee_id"], policy["leave_policy_id"])

        available = None
        if deducts:
            months = rules.months_accrued(emp["hire_date"], emp["termination_date"], raw["submitted"])
            accrued = rules.accrued_days(policy["annual_days"], policy["accrual_per_month"], months)
            available = ctx["openings"][key] + accrued - held.get(key, 0)

        clashes = [rid for (s, e, rid) in live.get(emp["employee_id"], [])
                   if ranges_overlap(raw["start"], raw["end"], s, e)]
        failed = rules.leave_failed_checks(business_days, deducts, available,
                                           policy["max_consecutive_days"], bool(clashes))
        overridden = raw["id"] in overrides
        screening_code = failed[0] if (failed and not overridden) else None

        facts = {"business_days": business_days, "leave_type": raw["leave_type"]}
        plans = []
        if screening_code:
            status, final_date, final_code = "REJECTED", raw["submitted"], screening_code
        else:
            plans = build_plans("LEAVE", facts, ctx, emp, raw["submitted"],
                                lambda role: rules.leave_step_decision(role))
            timing = random.Random(f"{ctx['seed']}-{raw['id']}")        # per-request timing, order independent
            status, final_date = rules.walk_steps(plans, raw["submitted"], timing, C.AS_OF_DATE)
            if status == "APPROVED":
                final_code = "APPROVED_BY_OVERRIDE" if overridden else "APPROVED_WITHIN_POLICY"
            else:
                final_code = "AWAITING_APPROVAL"

        if status != "REJECTED":                      # approved or still pending -> days are held
            if deducts:
                held[key] = held.get(key, 0) + business_days
            live.setdefault(emp["employee_id"], []).append((raw["start"], raw["end"], raw["id"]))

        row = {
            "leave_request_id": raw["id"], "employee_id": emp["employee_id"],
            "leave_policy_id": policy["leave_policy_id"], "start_date": raw["start"], "end_date": raw["end"],
            "calendar_days": calendar_days, "business_days": business_days,
            "submitted_date": raw["submitted"], "request_reason": raw["reason"],
            "balance_at_submission": available, "status": status,
            "final_reason_code": final_code, "final_decision_date": final_date,
        }
        note = f"business days = {business_days}, available = {available}, overlaps = {clashes}"
        results.append({
            "row": row, "plans": plans, "failed": failed, "overridden": overridden, "clashes": clashes,
            "steps": step_rows("leave", raw["id"], plans),
            "events": status_events("leave", raw["id"], emp["employee_id"], raw["submitted"], plans,
                                    status, final_date, final_code, screening_code, note),
        })
    return results


def build_balances(employees, policy_rows, openings, results, make_id):
    """
    leave_balances: one row per employee and balance-bearing policy.
    Every number is derived: used / pending come from the requests, accrual from the hire date.
    """
    used, pending = {}, {}
    for result in results:
        row = result["row"]
        key = (row["employee_id"], row["leave_policy_id"])
        if row["balance_at_submission"] is None:
            continue                                   # unpaid leave has no balance
        if row["status"] == "APPROVED":
            used[key] = used.get(key, 0) + row["business_days"]
        elif row["status"] == "PENDING_APPROVAL":
            pending[key] = pending.get(key, 0) + row["business_days"]
    policies = {p["leave_policy_id"]: p for p in policy_rows}
    emp_by_id = {e["employee_id"]: e for e in employees}
    balances = []
    for number, ((emp_id_, policy_id), opening) in enumerate(sorted(openings.items()), start=1):
        emp, policy = emp_by_id[emp_id_], policies[policy_id]
        months = rules.months_accrued(emp["hire_date"], emp["termination_date"], C.AS_OF_DATE)
        accrued = rules.accrued_days(policy["annual_days"], policy["accrual_per_month"], months)
        used_days = used.get((emp_id_, policy_id), 0)
        pending_days = pending.get((emp_id_, policy_id), 0)
        balances.append({
            "leave_balance_id": make_id(number), "employee_id": emp_id_, "leave_policy_id": policy_id,
            "balance_year": C.YEAR, "opening_balance": opening, "accrued_days": accrued,
            "used_days": used_days, "pending_days": pending_days,
            "available_days": round(opening + accrued - used_days - pending_days, 2),
            "as_of_date": C.AS_OF_DATE,
        })
    return balances
