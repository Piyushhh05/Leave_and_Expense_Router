"""
services.py - the BUSINESS ACTIONS of the application (views only call these).

  leave_preview / expense_preview   show what the router would do, without saving anything
  submit_leave / submit_expense     save a new request: screening -> routing -> steps -> events
  decide_step                       an approver approves or rejects the step that is PENDING

The decision rules themselves are NOT written here: they come from generator/rules.py,
the same file the data generator and the audit script use.
"""
import hashlib
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Sum

from generator import config as C
from generator import rules
from generator.flow_common import build_plans, status_events, step_rows
from generator.helpers import claim_id, count_days, event_id, leave_id, line_id, reimbursement_id
from workflow.models import (ApprovalRule, ApprovalStep, Employee, ExpenseClaim, ExpenseLine, ExpensePolicy,
                             Holiday, LeaveBalance, LeavePolicy, LeaveRequest, Reimbursement, StatusEvent)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def next_number(model):
    """Next counter for an ID like 'LVE-2026-000801'. IDs are zero padded, so the largest ID text is the newest."""
    pk_name = model._meta.pk.name
    newest = model.objects.order_by("-" + pk_name).values_list(pk_name, flat=True).first()
    return int(newest.split("-")[-1]) + 1 if newest else 1


def plan_context(requester):
    """What build_plans() needs: routing rules, the requester + manager as plain dicts, special-role holders."""
    people = {requester.employee_id: {"employee_id": requester.employee_id, "manager_id": requester.manager_id}}
    if requester.manager_id:
        boss = requester.manager
        people[boss.employee_id] = {"employee_id": boss.employee_id, "manager_id": boss.manager_id}
    holders = {e.special_role: e.employee_id for e in Employee.objects.exclude(special_role=None)}
    return {"rules": list(ApprovalRule.objects.order_by("approval_rule_id").values()), "emp": people,
            "holders": holders}, people[requester.employee_id]


def open_plans(plans):
    """A new request: the first real step is PENDING, later ones WAITING, same-person steps SKIPPED."""
    first_found = False
    for plan in plans:
        plan["decided_date"], plan["code"], plan["text"] = None, None, None
        if plan["same_as"] is not None:
            plan["status"] = "SKIPPED"
            plan["code"] = "SAME_APPROVER_EARLIER_STEP"
            plan["text"] = f"Same person already decides in step {plan['same_as'] + 1}"
        elif not first_found:
            plan["status"], first_found = "PENDING", True
        else:
            plan["status"] = "WAITING"


def plan_view(plans):
    """Plans as simple dictionaries for the web page / JSON."""
    names = {e.employee_id: e.full_name for e in Employee.objects.filter(employee_id__in=[p["approver_id"] for p in plans])}
    return [{"step": i + 1, "role": p["role"], "rule": p["rule"]["approval_rule_id"], "why": p["routing_text"],
             "approver_id": p["approver_id"], "approver_name": names.get(p["approver_id"], ""),
             "duplicate": p["same_as"] is not None, "planned": p["planned_status"], "planned_code": p["planned_code"]}
            for i, p in enumerate(plans)]


def save_steps_and_events(kind, entity_id, requester_id, submitted, plans, status, final_date, final_code, screening_code, note):
    """Writes approval_steps and status_events rows (history is only ever appended)."""
    for row in step_rows(kind, entity_id, plans):
        ApprovalStep.objects.create(**row)
    number = next_number(StatusEvent)
    for event in status_events(kind, entity_id, requester_id, submitted, plans, status, final_date, final_code,
                               screening_code, note):
        event.pop("order")
        StatusEvent.objects.create(event_id=event_id(number), **event)
        number += 1


def refresh_balance(employee_id, policy_id):
    """Re-derives used / pending / available of one balance row from the requests."""
    balance = LeaveBalance.objects.filter(employee_id=employee_id, leave_policy_id=policy_id).first()
    if balance is None:
        return
    mine = LeaveRequest.objects.filter(employee_id=employee_id, leave_policy_id=policy_id)
    used = mine.filter(status="APPROVED").aggregate(t=Sum("business_days"))["t"] or 0
    pending = mine.filter(status="PENDING_APPROVAL").aggregate(t=Sum("business_days"))["t"] or 0
    LeaveBalance.objects.filter(pk=balance.pk).update(
        used_days=used, pending_days=pending, available_days=balance.opening_balance + balance.accrued_days - used - pending)


# ---------------------------------------------------------------------------
# LEAVE
# ---------------------------------------------------------------------------
def leave_preview(employee, leave_type, start, end):
    errors = []
    if end < start:
        errors.append("End date is before start date")
    if employee.status != "ACTIVE":
        errors.append("Employee is no longer active")
    if start < employee.hire_date:
        errors.append("Leave starts before the hire date")
    if errors:
        return {"errors": errors}
    policy_id = C.ANNUAL_POLICY_BY_COUNTRY[employee.country] if leave_type == "ANNUAL" else C.POLICY_BY_TYPE[leave_type]
    policy = LeavePolicy.objects.get(pk=policy_id)
    holidays = set(Holiday.objects.filter(country=employee.country).values_list("holiday_date", flat=True))
    calendar_days, business_days = count_days(start, end, holidays)

    available = None
    if policy.deducts_balance:
        available = float(LeaveBalance.objects.get(employee=employee, leave_policy=policy).available_days)
    clashes = list(LeaveRequest.objects.filter(employee=employee, status__in=["APPROVED", "PENDING_APPROVAL"],
                                               start_date__lte=end, end_date__gte=start).values_list("pk", flat=True))
    failed = rules.leave_failed_checks(business_days, policy.deducts_balance, available, policy.max_consecutive_days, bool(clashes))

    facts = {"business_days": business_days, "leave_type": leave_type}
    plans = []
    if not failed:
        ctx, requester = plan_context(employee)
        plans = build_plans("LEAVE", facts, ctx, requester, date.today(), rules.leave_step_decision)
        open_plans(plans)
    return {"errors": [], "policy": policy, "calendar_days": calendar_days, "business_days": business_days,
            "available": available, "clashes": clashes, "failed": failed, "plans": plans}


@transaction.atomic
def submit_leave(employee, leave_type, start, end, reason):
    pv = leave_preview(employee, leave_type, start, end)
    if pv["errors"]:
        raise ValueError("; ".join(pv["errors"]))
    today = date.today()
    request_id = leave_id(next_number(LeaveRequest))
    failed = pv["failed"]
    if failed:
        status, final_date, final_code = "REJECTED", today, failed[0]
    else:
        status, final_date, final_code = "PENDING_APPROVAL", None, "AWAITING_APPROVAL"
    LeaveRequest.objects.create(
        leave_request_id=request_id, employee=employee, leave_policy=pv["policy"], start_date=start, end_date=end,
        calendar_days=pv["calendar_days"], business_days=pv["business_days"], submitted_date=today,
        request_reason=reason[:80] or "Not stated", balance_at_submission=pv["available"], status=status,
        final_reason_code=final_code, final_decision_date=final_date)
    note = f"business days = {pv['business_days']}, available = {pv['available']}"
    save_steps_and_events("leave", request_id, employee.employee_id, today, pv["plans"], status, final_date,
                          final_code, failed[0] if failed else None, note)
    refresh_balance(employee.employee_id, pv["policy"].pk)
    return request_id


# ---------------------------------------------------------------------------
# EXPENSE
# ---------------------------------------------------------------------------
def expense_preview(employee, purpose, raw_lines):
    """raw_lines = [{category, amount, expense_date, receipt_no}]"""
    errors = []
    if not 1 <= len(raw_lines) <= 10:
        errors.append("A claim needs 1 to 10 lines")
    if employee.status != "ACTIVE":
        errors.append("Employee is no longer active")
    policies = {p.category: p for p in ExpensePolicy.objects.all()}
    lines = []
    for number, raw in enumerate(raw_lines, start=1):
        policy = policies.get(raw["category"])
        if policy is None or raw["amount"] <= 0:
            errors.append(f"Line {number}: choose a category and an amount above 0")
            continue
        receipt_no = raw.get("receipt_no", "").strip().lower()
        lines.append({
            "line_no": number, "category": policy.category, "expense_policy_id": policy.pk,
            "expense_date": raw["expense_date"], "amount": round(float(raw["amount"]), 2),
            "receipt_provided": bool(receipt_no),
            "receipt_hash": hashlib.sha256(receipt_no.encode()).hexdigest()[:16] if receipt_no else None,
        })
    if errors:
        return {"errors": errors}

    policy_by_id = {p.pk: {"max_line_amount": p.max_line_amount, "receipt_required_above": p.receipt_required_above}
                    for p in policies.values()}
    total = round(sum(l["amount"] for l in lines), 2)
    worst = rules.worst_line_status(lines, policy_by_id)
    missing = rules.has_missing_receipt(lines, policy_by_id)
    hashes = [l["receipt_hash"] for l in lines if l["receipt_hash"]]
    duplicate = len(set(hashes)) < len(hashes) or ExpenseLine.objects.filter(receipt_hash__in=hashes).exists()
    today = date.today()
    outside = any(l["expense_date"] < employee.hire_date or l["expense_date"] > today or
                  (employee.termination_date and l["expense_date"] > employee.termination_date) for l in lines)

    center = employee.cost_center
    committed = float(ExpenseClaim.objects.filter(cost_center=center).filter(status__in=["APPROVED", "REIMBURSED"])
                      .aggregate(t=Sum("total_amount"))["t"] or 0)
    exceeded, overshoot = rules.budget_position(committed, total, float(center.annual_budget))
    failed = rules.claim_failed_checks(True, outside, missing, duplicate)

    facts = {"total": total, "categories": {l["category"] for l in lines}, "country": employee.country,
             "policy_breach": worst != "WITHIN", "budget_exceeded": exceeded, "worst_line": worst, "overshoot": overshoot}
    plans, outcome = [], "REJECTED at screening: " + failed[0] if failed else ""
    if not failed:
        ctx, requester = plan_context(employee)
        plans = build_plans("EXPENSE", facts, ctx, requester, today, lambda role: rules.expense_step_decision(role, facts))
        open_plans(plans)
        rejecting = [p for p in plans if p["same_as"] is None and p["planned_status"] == "REJECTED"]
        outcome = (f"Expected to be REJECTED at {rejecting[0]['role']} ({rejecting[0]['planned_code']})" if rejecting
                   else "Expected to be APPROVED if every approver agrees")
    return {"errors": [], "lines": lines, "total": total, "worst": worst, "failed": failed, "plans": plans,
            "budget_exceeded": exceeded, "overshoot": overshoot, "center": center, "outcome": outcome, "facts": facts}


@transaction.atomic
def submit_expense(employee, purpose, raw_lines):
    pv = expense_preview(employee, purpose, raw_lines)
    if pv["errors"]:
        raise ValueError("; ".join(pv["errors"]))
    today = date.today()
    claim = claim_id(next_number(ExpenseClaim))
    failed = pv["failed"]
    if failed:
        status, final_date, final_code = "REJECTED", today, failed[0]
    else:
        status, final_date, final_code = "PENDING_APPROVAL", None, "AWAITING_APPROVAL"
    ExpenseClaim.objects.create(
        expense_claim_id=claim, employee=employee, cost_center=pv["center"], employee_country=employee.country,
        submitted_date=today, purpose=purpose[:80] or "Not stated", currency="USD", total_amount=pv["total"],
        line_count=len(pv["lines"]), has_policy_breach=pv["worst"] != "WITHIN", budget_exceeded=pv["budget_exceeded"],
        status=status, final_reason_code=final_code, final_decision_date=final_date)
    for l in pv["lines"]:
        ExpenseLine.objects.create(
            expense_line_id=line_id(claim, l["line_no"]), expense_claim_id=claim, line_no=l["line_no"],
            expense_policy_id=l["expense_policy_id"], expense_date=l["expense_date"], merchant="Entered in web form",
            amount=l["amount"], receipt_provided=l["receipt_provided"],
            receipt_file_name=f"{claim}_L{l['line_no']:02d}.pdf" if l["receipt_provided"] else None,
            receipt_hash=l["receipt_hash"])
    note = "Screening failed: " + ", ".join(failed) if failed else ""
    save_steps_and_events("expense", claim, employee.employee_id, today, pv["plans"], status, final_date,
                          final_code, failed[0] if failed else None, note)
    return claim


# ---------------------------------------------------------------------------
# APPROVER DECISION
# ---------------------------------------------------------------------------
def add_event(kind, request, from_status, to_status, actor, code, note):
    key = {"leave_request": request} if kind == "leave" else {"expense_claim": request}
    StatusEvent.objects.create(event_id=event_id(next_number(StatusEvent)), from_status=from_status,
                               to_status=to_status, event_date=date.today(), actor_type="EMPLOYEE" if actor else "SYSTEM",
                               actor=actor, reason_code=code, note=note[:200], **key)


@transaction.atomic
def decide_step(step_id, approver_id, action, comment):
    """
    An approver approves or rejects the step that is PENDING for them.
    Guards: step must be PENDING, the approver must be the assigned person,
    nobody approves their own request, and policy limits cannot be waved through.
    """
    step = ApprovalStep.objects.select_for_update().get(pk=step_id)
    kind = "leave" if step.leave_request_id else "expense"
    request = step.leave_request or step.expense_claim
    if step.status != "PENDING":
        raise ValueError("This step is not waiting for a decision")
    if step.approver_id != approver_id:
        raise ValueError("This step is assigned to someone else")
    if request.employee_id == approver_id:
        raise ValueError("Nobody can approve their own request")

    today = date.today()
    if action == "APPROVE":
        if kind == "leave":
            status, code, text = rules.leave_step_decision(step.approver_role)
        else:
            lines = [{"amount": l.amount, "expense_policy_id": l.expense_policy_id} for l in request.lines.all()]
            policy_by_id = {p.pk: {"max_line_amount": p.max_line_amount} for p in ExpensePolicy.objects.all()}
            facts = {"worst_line": rules.worst_line_status(lines, policy_by_id),
                     "budget_exceeded": request.budget_exceeded, "overshoot": 0}
            status, code, text = rules.expense_step_decision(step.approver_role, facts)
            if status == "REJECTED":
                raise ValueError("Policy does not allow approval: " + text)
        step.status, step.decision_reason_code, step.decision_reason = "APPROVED", code, comment or text
    else:
        step.status, step.decision_reason_code = "REJECTED", "REJECTED_BY_APPROVER"
        step.decision_reason = comment or "Rejected by approver"
    step.decided_date = today
    step.save()

    siblings = list(request.steps.order_by("step_no"))
    after = [s for s in siblings if s.step_no > step.step_no]
    if step.status == "REJECTED":
        for s in after:
            if s.status in ("WAITING", "PENDING"):
                s.status, s.decision_reason_code = "SKIPPED", "EARLIER_STEP_REJECTED"
                s.decision_reason = "An earlier step was rejected"
                s.save()
        finish(kind, request, "REJECTED", "REJECTED_BY_APPROVER", step.approver, step.decision_reason)
        return "Request rejected"

    waiting = [s for s in after if s.status == "WAITING"]
    if waiting:
        waiting[0].status = "PENDING"
        waiting[0].save()
        return f"Approved. Next approver: {waiting[0].approver_role}"
    codes = [s.decision_reason_code for s in siblings if s.status == "APPROVED"]
    final_code = "APPROVED_WITHIN_POLICY" if kind == "leave" else rules.claim_final_code(codes)
    finish(kind, request, "APPROVED", final_code, step.approver, step.decision_reason)
    return "Request fully approved" + (" - reimbursement scheduled" if kind == "expense" else "")


def finish(kind, request, status, code, actor, note):
    """Final status change: update the request, append an event, then the follow-up (balance / payment)."""
    old = request.status
    request.status, request.final_reason_code, request.final_decision_date = status, code, date.today()
    request.save()
    add_event(kind, request, old, status, actor, code, note or "")
    if kind == "leave":
        refresh_balance(request.employee_id, request.leave_policy_id)
    elif status == "APPROVED":       # reimbursement exists only after final approval
        Reimbursement.objects.create(
            reimbursement_id=reimbursement_id(next_number(Reimbursement)), expense_claim=request,
            employee_id=request.employee_id, amount=request.total_amount, currency="USD",
            payment_method="BANK_TRANSFER", approved_date=date.today(),
            payment_date=date.today() + timedelta(days=5),
            status="SCHEDULED")
