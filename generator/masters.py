"""
masters.py - STEP 1 of the workflow: master (parent) data.

Creates holidays, employees (with the manager hierarchy), cost centres,
leave policies, expense policies and the opening leave balances.
Everything here is created BEFORE any request, so requests can point to valid parents.
"""
from datetime import date

from generator import config as C
from generator.helpers import emp_id, random_date


def make_holidays():
    rows = []
    for i, (country, day, name) in enumerate(C.HOLIDAYS, start=1):
        rows.append({"holiday_id": f"HOL-{i:03d}", "holiday_date": day, "country": country, "name": name})
    return rows


def make_leave_policies():
    rows = []
    for pid, name, kind, countries, annual, per_month, cap, max_days, deducts in C.LEAVE_POLICIES:
        rows.append({
            "leave_policy_id": pid, "name": name, "leave_type": kind,
            "applies_to_countries": countries, "annual_days": annual,
            "accrual_per_month": per_month, "carry_forward_cap": cap,
            "max_consecutive_days": max_days, "deducts_balance": deducts,
            "effective_from": date(2025, 1, 1), "effective_to": None,
        })
    return rows


def make_expense_policies():
    rows = []
    for pid, category, max_line, receipt_above in C.EXPENSE_POLICIES:
        rows.append({
            "expense_policy_id": pid, "category": category, "max_line_amount": max_line,
            "receipt_required_above": receipt_above,
            "effective_from": date(2025, 1, 1), "effective_to": None,
        })
    return rows


def make_employees(rng, total):
    """
    Hierarchy (every person has a manager one level above):
        CEO (5) <- VP (4, one per department) <- Director (3) <- Manager (2) <- Staff (1)
    IDs are handed out top-down, so a manager's ID is always smaller than the report's.
    """
    n_dept = len(C.DEPARTMENTS)
    n_directors = max(n_dept, round(total * C.DIRECTOR_SHARE))
    n_managers = max(2 * n_dept, round(total * C.MANAGER_SHARE))
    n_staff = total - 1 - n_dept - n_directors - n_managers
    assert n_staff >= 10, "scale too small: need at least ~40 employees"

    rows = []

    def add(level, dept, country, hire, manager_id, special_role=None):
        number = len(rows) + 1
        first, last = rng.choice(C.FIRST_NAMES), rng.choice(C.LAST_NAMES)
        row = {
            "employee_id": emp_id(number),
            "full_name": f"{first} {last}",
            "email": f"{first}.{last}.{number}@example.com".lower(),   # example.com is reserved, no real mailbox
            "country": country,
            "department": dept,
            "job_level": level,
            "job_title": C.JOB_TITLES[level],
            "manager_id": manager_id,
            "cost_center_id": None,           # filled in once cost centres exist
            "hire_date": hire,
            "termination_date": None,
            "status": "ACTIVE",
            "special_role": special_role,
        }
        rows.append(row)
        return row

    def pick_country():
        return rng.choices(C.COUNTRIES, C.COUNTRY_WEIGHTS)[0]

    ceo = add(5, "Executive", "US", date(2015, 1, 5), None)

    vps = {}
    for dept in C.DEPARTMENTS:
        special = {"Finance": "CFO", "HR": "HR_HEAD"}.get(dept)
        vps[dept] = add(4, dept, pick_country(), random_date(rng, date(2016, 1, 1), date(2019, 12, 31)),
                        ceo["employee_id"], special)

    directors = {d: [] for d in C.DEPARTMENTS}
    controller_named = False
    for i in range(n_directors):
        dept = C.DEPARTMENTS[i % n_dept]
        special = None
        if dept == "Finance" and not controller_named:
            special, controller_named = "FINANCE_CONTROLLER", True
        directors[dept].append(add(3, dept, pick_country(),
                                   random_date(rng, date(2017, 1, 1), date(2022, 12, 31)),
                                   vps[dept]["employee_id"], special))

    managers = {d: [] for d in C.DEPARTMENTS}
    for i in range(n_managers):
        dept = C.DEPARTMENTS[i % n_dept]
        boss = rng.choice(directors[dept])
        managers[dept].append(add(2, dept, pick_country(),
                                  random_date(rng, date(2018, 1, 1), date(2024, 12, 31)), boss["employee_id"]))

    staff = []
    for _ in range(n_staff):
        dept = rng.choice(C.DEPARTMENTS)
        boss = rng.choice(managers[dept])
        staff.append(add(1, dept, pick_country(),
                         random_date(rng, date(2019, 1, 1), date(2025, 12, 31)), boss["employee_id"]))

    # Some staff joined during 2026, some already left (picked without overlap)
    picks = rng.sample(range(n_staff), round(n_staff * (C.NEW_HIRE_2026_SHARE_OF_STAFF + C.TERMINATED_SHARE_OF_STAFF)))
    n_new = round(n_staff * C.NEW_HIRE_2026_SHARE_OF_STAFF)
    for index in picks[:n_new]:
        staff[index]["hire_date"] = random_date(rng, date(2026, 2, 2), date(2026, 8, 14))
    for index in picks[n_new:]:
        staff[index]["termination_date"] = random_date(rng, date(2026, 3, 2), date(2026, 8, 15))
        staff[index]["status"] = "TERMINATED"
    return rows


def make_cost_centers(employees):
    """One cost centre per (department, country) plus one for the CEO. Budget = headcount x per-head amount."""
    combos = sorted({(e["department"], e["country"]) for e in employees if e["department"] != "Executive"})
    centers = [{"cost_center_id": "CC-000", "name": "Executive Office", "country": "US",
                "department": "Executive", "annual_budget": 0}]
    for number, (dept, country) in enumerate(combos, start=1):
        centers.append({"cost_center_id": f"CC-{number:03d}", "name": f"{dept} {country}",
                        "country": country, "department": dept, "annual_budget": 0})
    by_key = {(c["department"], c["country"]): c for c in centers}
    headcount = {c["cost_center_id"]: 0 for c in centers}
    for e in employees:
        center = by_key[(e["department"], e["country"])] if e["department"] != "Executive" else centers[0]
        e["cost_center_id"] = center["cost_center_id"]
        headcount[center["cost_center_id"]] += 1
    for c in centers:
        c["annual_budget"] = headcount[c["cost_center_id"]] * C.BUDGET_PER_HEAD
    return centers


def make_openings(rng, employees, policy_rows):
    """
    Opening (carry-forward) balance per employee and balance-bearing policy.
    Only ANNUAL leave carries forward, and only for people who joined before 2026.
    Returns {(employee_id, policy_id): days}.
    """
    policies = {p["leave_policy_id"]: p for p in policy_rows}
    openings = {}
    for e in employees:
        wanted = [C.ANNUAL_POLICY_BY_COUNTRY[e["country"]], C.POLICY_BY_TYPE["SICK"], C.POLICY_BY_TYPE["CASUAL"]]
        for pid in wanted:
            policy = policies[pid]
            carry = 0
            if policy["leave_type"] == "ANNUAL" and e["hire_date"] < date(C.YEAR, 1, 1):
                carry = rng.randint(0, int(policy["carry_forward_cap"]))
            openings[(e["employee_id"], pid)] = carry
    return openings


def can_raise_requests(employee):
    """Levels 1-3 raise requests. The finance controller is an approver only (see README)."""
    return employee["job_level"] <= 3 and employee["special_role"] != "FINANCE_CONTROLLER"


def role_holders(employees):
    """{'CFO': 'EMP-..', 'HR_HEAD': .., 'FINANCE_CONTROLLER': ..}"""
    return {e["special_role"]: e["employee_id"] for e in employees if e["special_role"]}
