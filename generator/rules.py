"""
rules.py - the BUSINESS RULES, written as small plain functions.

The same functions are used by
  * the generator   (to decide outcomes while creating data),
  * the audit script (to re-check the stored data),
  * the Django app   (to preview the route of a new request).
So there is exactly one place where a rule is defined.

Values can arrive as Python numbers (generator) or as text (CSV / database),
so the helpers below convert with float() / str() where needed.
"""
from datetime import date, timedelta

from generator import config as C
from generator.helpers import ranges_overlap  # noqa: F401  (re-exported for callers)

# The order in which approver roles appear in a path.
ROLE_ORDER = ["MANAGER", "SKIP_MANAGER", "FINANCE_CONTROLLER", "HR_HEAD", "CFO"]

# ---------------------------------------------------------------------------
# Approval rules as DATA. This list is written to approval_rules.csv, and the
# router reads the rows - so a policy change is a data change, not a code change.
# (id, domain, approver role, condition type, threshold, match value, min level, description)
# ---------------------------------------------------------------------------
APPROVAL_RULES = [
    ("APRL-L1", "LEAVE", "MANAGER", "ALWAYS", None, None, 2,
     "Every leave request needs the direct manager"),
    ("APRL-L2", "LEAVE", "SKIP_MANAGER", "DAYS_ABOVE", C.LEAVE_SKIP_LEVEL_ABOVE_DAYS, None, 3,
     f"More than {C.LEAVE_SKIP_LEVEL_ABOVE_DAYS} business days also needs the manager's manager"),
    ("APRL-L3", "LEAVE", "HR_HEAD", "DAYS_ABOVE", C.LEAVE_HR_ABOVE_DAYS, None, 4,
     f"More than {C.LEAVE_HR_ABOVE_DAYS} business days also needs the HR head"),
    ("APRL-L4", "LEAVE", "HR_HEAD", "LEAVE_TYPE", None, "UNPAID", 4,
     "Unpaid leave always needs the HR head"),
    ("APRL-E1", "EXPENSE", "MANAGER", "ALWAYS", None, None, 2,
     "Every expense claim needs the direct manager"),
    ("APRL-E2", "EXPENSE", "SKIP_MANAGER", "AMOUNT_ABOVE", C.EXPENSE_SKIP_LEVEL_ABOVE, None, 3,
     f"Claim total above {C.EXPENSE_SKIP_LEVEL_ABOVE} USD also needs the manager's manager"),
    ("APRL-E3", "EXPENSE", "SKIP_MANAGER", "CATEGORY", None, "CLIENT_ENTERTAINMENT", 3,
     "Client entertainment always needs the manager's manager"),
    ("APRL-E4", "EXPENSE", "FINANCE_CONTROLLER", "AMOUNT_ABOVE", C.EXPENSE_FINANCE_ABOVE, None, 3,
     f"Claim total above {C.EXPENSE_FINANCE_ABOVE} USD also needs the finance controller"),
    ("APRL-E5", "EXPENSE", "FINANCE_CONTROLLER", "POLICY_BREACH", None, None, 3,
     "A line above its policy limit needs the finance controller (exception path)"),
    ("APRL-E6", "EXPENSE", "FINANCE_CONTROLLER", "COUNTRY_AMOUNT", C.EXPENSE_REGIONAL_REVIEW_ABOVE,
     C.REGIONAL_REVIEW_COUNTRIES, 3,
     f"DE/UK claims above {C.EXPENSE_REGIONAL_REVIEW_ABOVE} USD need the finance controller"),
    ("APRL-E7", "EXPENSE", "CFO", "AMOUNT_ABOVE", C.EXPENSE_CFO_ABOVE, None, 4,
     f"Claim total above {C.EXPENSE_CFO_ABOVE} USD also needs the CFO"),
    ("APRL-E8", "EXPENSE", "CFO", "BUDGET_EXCEEDED", None, None, 4,
     "A claim that pushes its cost centre over budget needs the CFO"),
]
RULE_COLUMNS = ["approval_rule_id", "domain", "step_role", "condition_type", "threshold",
                "match_value", "min_approver_level", "description"]


def approval_rule_rows():
    """The rules as dictionaries (the shape of the approval_rules table)."""
    rows = []
    for values in APPROVAL_RULES:
        row = dict(zip(RULE_COLUMNS, values))
        row["effective_from"] = date(C.YEAR - 1, 1, 1)
        row["effective_to"] = None
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Small converters
# ---------------------------------------------------------------------------
def is_true(value):
    """CSV stores booleans as 1/0, Python as True/False."""
    return str(value) in ("1", "True")


def num(value):
    """Number from a float or a text cell."""
    return float(value)


# ---------------------------------------------------------------------------
# Leave accrual and balance
# ---------------------------------------------------------------------------
def months_accrued(hire_date, termination_date, as_of):
    """
    Leave is credited on the 1st of every month in which the person is employed.
    Count the 1st-of-month dates up to as_of where hire <= that date <= termination.
    """
    count = 0
    for month in range(1, as_of.month + 1):
        first = date(as_of.year, month, 1)
        employed = hire_date <= first and (termination_date is None or first <= termination_date)
        if employed and first <= as_of:
            count += 1
    return count


def accrued_days(annual_days, accrual_per_month, months):
    """Never more than the yearly entitlement. Values are multiples of 0.25 so floats are exact."""
    return min(float(annual_days), round(float(accrual_per_month) * months, 2))


def leave_failed_checks(business_days, deducts_balance, available, max_consecutive, overlaps):
    """Screening of a leave request. Returns the failed checks in priority order."""
    failed = []
    if business_days == 0:
        failed.append("NO_WORKING_DAYS")
    if overlaps:
        failed.append("OVERLAPPING_LEAVE")
    if deducts_balance and business_days > available:     # equal is allowed (boundary)
        failed.append("INSUFFICIENT_BALANCE")
    if business_days > max_consecutive:
        failed.append("EXCEEDS_MAX_CONSECUTIVE")
    return failed


# ---------------------------------------------------------------------------
# Expense checks
# ---------------------------------------------------------------------------
def line_policy_status(amount, max_line_amount):
    """WITHIN limit, TOLERATED (up to 120% - finance may approve) or BEYOND."""
    amount, limit = float(amount), float(max_line_amount)
    if amount <= limit:
        return "WITHIN"
    if amount <= limit * C.POLICY_EXCEPTION_TOLERANCE:
        return "TOLERATED"
    return "BEYOND"


def worst_line_status(lines, policy_by_id):
    """Worst policy status over all lines of a claim."""
    order = {"WITHIN": 0, "TOLERATED": 1, "BEYOND": 2}
    worst = "WITHIN"
    for line in lines:
        status = line_policy_status(line["amount"], policy_by_id[line["expense_policy_id"]]["max_line_amount"])
        if order[status] > order[worst]:
            worst = status
    return worst


def has_missing_receipt(lines, policy_by_id):
    """True if any line above its 'receipt required above' amount has no receipt."""
    for line in lines:
        limit = float(policy_by_id[line["expense_policy_id"]]["receipt_required_above"])
        if float(line["amount"]) > limit and not is_true(line["receipt_provided"]):
            return True
    return False


def claim_failed_checks(has_cost_center, outside_employment, missing_receipt, duplicate_hash):
    """Screening of an expense claim. Returns the failed checks in priority order."""
    failed = []
    if not has_cost_center:
        failed.append("MISSING_COST_CENTER")
    if outside_employment:
        failed.append("EXPENSE_OUTSIDE_EMPLOYMENT")
    if missing_receipt:
        failed.append("MISSING_RECEIPT")
    if duplicate_hash:
        failed.append("DUPLICATE_RECEIPT_HASH")
    return failed


def budget_position(committed, total, annual_budget):
    """Returns (exceeded, overshoot_fraction) for a cost centre. No cost centre -> not exceeded."""
    if annual_budget is None:
        return False, 0.0
    projected = committed + total
    if projected > annual_budget:
        return True, round((projected - annual_budget) / annual_budget, 4)
    return False, 0.0


# ---------------------------------------------------------------------------
# Routing: which approver roles are needed
# ---------------------------------------------------------------------------
def rule_in_force(rule, on_date):
    """ISO dates (YYYY-MM-DD) sort the same as text, so str() comparison is enough."""
    start_ok = str(rule["effective_from"]) <= str(on_date)
    end_ok = not rule["effective_to"] or str(rule["effective_to"]) >= str(on_date)
    return start_ok and end_ok


def rule_matches(rule, facts):
    """Does one rule apply to these facts?"""
    kind = rule["condition_type"]
    if kind == "ALWAYS":
        return True
    if kind == "DAYS_ABOVE":
        return facts["business_days"] > num(rule["threshold"])
    if kind == "LEAVE_TYPE":
        return facts["leave_type"] == rule["match_value"]
    if kind == "AMOUNT_ABOVE":
        return facts["total"] > num(rule["threshold"])
    if kind == "CATEGORY":
        return rule["match_value"] in facts["categories"]
    if kind == "COUNTRY_AMOUNT":
        return facts["country"] in rule["match_value"].split("|") and facts["total"] > num(rule["threshold"])
    if kind == "POLICY_BREACH":
        return facts["policy_breach"]
    if kind == "BUDGET_EXCEEDED":
        return facts["budget_exceeded"]
    raise ValueError("unknown condition type " + kind)


def required_steps(domain, facts, rules, on_date):
    """
    Returns [(role, rule)] in ROLE_ORDER. A role appears once, tied to the FIRST
    rule (lowest id) that required it - that rule is stored on the approval step.
    """
    chosen = {}
    for rule in rules:
        if rule["domain"] != domain or not rule_in_force(rule, on_date):
            continue
        if rule["step_role"] not in chosen and rule_matches(rule, facts):
            chosen[rule["step_role"]] = rule
    return [(role, chosen[role]) for role in ROLE_ORDER if role in chosen]


def routing_text(rule, domain, facts):
    """Human readable 'why does this step exist'."""
    if domain == "LEAVE":
        detail = f"business days = {facts['business_days']}, type = {facts['leave_type']}"
    else:
        detail = f"total = {facts['total']:.2f} USD, country = {facts['country']}"
    return f"{rule['approval_rule_id']}: {rule['description']} ({detail})"


def resolve_approver(role, requester, employees_by_id, role_holders):
    """
    Who is the approver for a role?
      MANAGER      -> the requester's manager
      SKIP_MANAGER -> the manager's manager
      other roles  -> the one employee who holds that special role
    """
    if role == "MANAGER":
        return requester["manager_id"]
    if role == "SKIP_MANAGER":
        return employees_by_id[requester["manager_id"]]["manager_id"]
    return role_holders[role]


# ---------------------------------------------------------------------------
# Decisions of an approval step
# ---------------------------------------------------------------------------
def leave_step_decision(role):
    """Leave approvers approve once a request has passed screening."""
    return "APPROVED", "APPROVED_WITHIN_POLICY", "Request is within policy and balance"


def expense_step_decision(role, facts):
    """
    Returns (status, reason_code, text) for one expense step.
      Finance controller: line > 120% of limit -> reject; up to 120% -> approve as exception.
      CFO: budget overshoot > 10% -> reject; otherwise approve as budget exception.
    """
    if role == "FINANCE_CONTROLLER":
        if facts["worst_line"] == "BEYOND":
            return "REJECTED", "POLICY_LIMIT_BREACH", "A line is more than 120% of its policy limit"
        if facts["worst_line"] == "TOLERATED":
            return "APPROVED", "APPROVED_POLICY_EXCEPTION", "Line is up to 120% of its limit - approved as exception"
    if role == "CFO" and facts["budget_exceeded"]:
        if facts["overshoot"] > C.BUDGET_OVERSHOOT_LIMIT:
            return "REJECTED", "BUDGET_EXCEEDED", "Cost centre would exceed its budget by more than 10%"
        return "APPROVED", "APPROVED_BUDGET_EXCEPTION", "Cost centre over budget by up to 10% - approved as exception"
    return "APPROVED", "APPROVED_WITHIN_POLICY", "Claim is within policy"


def claim_final_code(step_codes):
    """Reason code of a fully approved claim. Policy exception wins over budget exception."""
    if "APPROVED_POLICY_EXCEPTION" in step_codes:
        return "APPROVED_POLICY_EXCEPTION"
    if "APPROVED_BUDGET_EXCEPTION" in step_codes:
        return "APPROVED_BUDGET_EXCEPTION"
    return "APPROVED_WITHIN_POLICY"


def walk_steps(plans, submitted_date, timing_rng, as_of):
    """
    Moves a request through its approval steps in time.

    plans = list of dicts with: planned_status, planned_code, planned_text, same_as (index or None)
    It fills in status / decided_date / decision_reason_code / decision_reason on each plan
    and returns (final_status, final_date):
      * a step is decided 1-3 days after the previous one,
      * a decision that would fall after the as-of date has not happened yet -> PENDING (then WAITING),
      * after a rejection the remaining steps are SKIPPED.
    """
    current = submitted_date
    blocked = False      # an earlier step is still PENDING
    rejected = False
    for i, plan in enumerate(plans):
        plan["decided_date"] = None
        if plan["same_as"] is not None:
            plan["status"] = "SKIPPED"
            plan["code"] = "SAME_APPROVER_EARLIER_STEP"
            plan["text"] = f"Same person already decides in step {plan['same_as'] + 1}"
            continue
        if rejected:
            plan["status"] = "SKIPPED"
            plan["code"] = "EARLIER_STEP_REJECTED"
            plan["text"] = "An earlier step was rejected"
            continue
        if blocked:
            plan["status"], plan["code"], plan["text"] = "WAITING", None, None
            continue
        decided = current + timedelta(days=timing_rng.randint(*C.STEP_TURNAROUND_DAYS))
        if decided > as_of:
            plan["status"], plan["code"], plan["text"] = "PENDING", None, None
            blocked = True
            continue
        plan["status"] = plan["planned_status"]
        plan["code"] = plan["planned_code"]
        plan["text"] = plan["planned_text"]
        plan["decided_date"] = decided
        current = decided
        if plan["status"] == "REJECTED":
            rejected = True
    if rejected:
        return "REJECTED", current
    if blocked:
        return "PENDING_APPROVAL", None
    return "APPROVED", current


def touches_weekend_or_holiday(start, end, holiday_dates):
    """True if the range starts/ends on a weekend or holiday, or contains a public holiday."""
    if start.weekday() >= 5 or end.weekday() >= 5 or start in holiday_dates or end in holiday_dates:
        return True
    return any(start <= h <= end for h in holiday_dates)
