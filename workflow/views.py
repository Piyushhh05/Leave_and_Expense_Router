"""
views.py - one function per web page. Each view gets data with the Django ORM and
hands it to a template. Business actions live in services.py.
"""
import json
from datetime import date

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from generator import config as C
from generator import rules
from workflow import services
from workflow.models import (ApprovalRule, ApprovalStep, CostCenter, DetectedException, Employee, ExpenseClaim,
                             ExpensePolicy, GroundTruth, LeaveBalance, LeavePolicy, LeaveRequest, Reimbursement)


def counts(queryset, field):
    """{'APPROVED': 12, ...} for one column."""
    return {row[field]: row["n"] for row in queryset.values(field).annotate(n=Count("pk")).order_by("-n")}


def paginate(request, queryset, per_page=25):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


# ---------------------------------------------------------------------------
# Dashboard (process owner)
# ---------------------------------------------------------------------------
def dashboard(request):
    claims = ExpenseClaim.objects
    spent = {row["cost_center_id"]: row["t"] for row in
             claims.filter(status__in=["APPROVED", "REIMBURSED"]).values("cost_center_id").annotate(t=Sum("total_amount"))}
    budgets = []
    for cc in CostCenter.objects.exclude(pk="CC-000"):
        used = float(spent.get(cc.pk) or 0)
        budgets.append({"cc": cc, "used": used, "pct": round(100 * used / float(cc.annual_budget))})
    budgets.sort(key=lambda b: -b["pct"])

    steps_per_claim = (ApprovalStep.objects.filter(expense_claim__isnull=False).values("expense_claim_id")
                       .annotate(n=Count("pk")))
    path_lengths = {}
    for row in steps_per_claim:
        path_lengths[row["n"]] = path_lengths.get(row["n"], 0) + 1
    path_lengths[0] = claims.count() - len(steps_per_claim)          # rejected at screening: no steps at all
    context = {
        "n_employees": Employee.objects.count(),
        "n_leave": LeaveRequest.objects.count(),
        "n_claims": claims.count(),
        "pending_leave": LeaveRequest.objects.filter(status="PENDING_APPROVAL").count(),
        "pending_claims": claims.filter(status="PENDING_APPROVAL").count(),
        "paid_total": Reimbursement.objects.filter(status="PAID").aggregate(t=Sum("amount"))["t"] or 0,
        "leave_status": counts(LeaveRequest.objects, "status"),
        "claim_status": counts(claims, "status"),
        "leave_reasons": counts(LeaveRequest.objects.exclude(status="PENDING_APPROVAL"), "final_reason_code"),
        "claim_reasons": counts(claims.exclude(status="PENDING_APPROVAL"), "final_reason_code"),
        "path_lengths": sorted(path_lengths.items()),
        "budgets": budgets[:8],
        "detections": counts(DetectedException.objects, "issue_type"),
    }
    return render(request, "workflow/dashboard.html", context)


# ---------------------------------------------------------------------------
# Leave
# ---------------------------------------------------------------------------
def leave_list(request):
    rows = LeaveRequest.objects.select_related("employee", "leave_policy").order_by("-leave_request_id")
    status, reason, q = request.GET.get("status", ""), request.GET.get("reason", ""), request.GET.get("q", "")
    if status:
        rows = rows.filter(status=status)
    if reason:
        rows = rows.filter(final_reason_code=reason)
    if q:
        rows = rows.filter(Q(employee__full_name__icontains=q) | Q(employee__employee_id__icontains=q) | Q(pk__icontains=q))
    context = {"page": paginate(request, rows), "status": status, "reason": reason, "q": q,
               "statuses": ["SUBMITTED", "PENDING_APPROVAL", "APPROVED", "REJECTED"],
               "reasons": sorted(counts(LeaveRequest.objects, "final_reason_code"))}
    return render(request, "workflow/leave_list.html", context)


def leave_detail(request, pk):
    leave = get_object_or_404(LeaveRequest.objects.select_related("employee", "leave_policy"), pk=pk)
    balance = LeaveBalance.objects.filter(employee=leave.employee, leave_policy=leave.leave_policy).first()
    return render(request, "workflow/leave_detail.html", {
        "leave": leave, "balance": balance,
        "steps": leave.steps.select_related("approver", "approval_rule"),
        "events": leave.events.select_related("actor"),
        "weekend_days": leave.calendar_days - leave.business_days,
    })


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------
def expense_list(request):
    rows = ExpenseClaim.objects.select_related("employee").order_by("-expense_claim_id")
    status, reason, q = request.GET.get("status", ""), request.GET.get("reason", ""), request.GET.get("q", "")
    if status:
        rows = rows.filter(status=status)
    if reason:
        rows = rows.filter(final_reason_code=reason)
    if q:
        rows = rows.filter(Q(employee__full_name__icontains=q) | Q(employee__employee_id__icontains=q) | Q(pk__icontains=q))
    context = {"page": paginate(request, rows), "status": status, "reason": reason, "q": q,
               "statuses": ["SUBMITTED", "PENDING_APPROVAL", "APPROVED", "REJECTED", "REIMBURSED"],
               "reasons": sorted(counts(ExpenseClaim.objects, "final_reason_code"))}
    return render(request, "workflow/expense_list.html", context)


def expense_detail(request, pk):
    claim = get_object_or_404(ExpenseClaim.objects.select_related("employee", "cost_center"), pk=pk)
    lines = []
    for line in claim.lines.select_related("expense_policy"):
        limit = line.expense_policy.max_line_amount
        lines.append({"line": line, "limit": limit, "policy_status": rules.line_policy_status(line.amount, limit),
                      "receipt_needed": line.amount > line.expense_policy.receipt_required_above})
    spent = ExpenseClaim.objects.filter(cost_center=claim.cost_center, status__in=["APPROVED", "REIMBURSED"]).aggregate(
        t=Sum("total_amount"))["t"] if claim.cost_center else None
    return render(request, "workflow/expense_detail.html", {
        "claim": claim, "lines": lines, "cost_center_spent": spent,
        "steps": claim.steps.select_related("approver", "approval_rule"),
        "events": claim.events.select_related("actor"),
        "reimbursements": claim.reimbursements.all(),
    })


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------
def employee_list(request):
    q = request.GET.get("q", "")
    rows = Employee.objects.select_related("manager", "cost_center").order_by("employee_id")
    if q:
        rows = rows.filter(Q(full_name__icontains=q) | Q(pk__icontains=q) | Q(department__icontains=q))
    return render(request, "workflow/employee_list.html", {"page": paginate(request, rows), "q": q})


def employee_detail(request, pk):
    employee = get_object_or_404(Employee.objects.select_related("manager", "cost_center"), pk=pk)
    chain, boss = [], employee.manager
    while boss:
        chain.append(boss)
        boss = boss.manager
    return render(request, "workflow/employee_detail.html", {
        "e": employee, "chain": chain, "n_reports": employee.reports.count(),
        "balances": employee.balances.select_related("leave_policy"),
        "leaves": employee.leave_requests.order_by("-leave_request_id")[:8],
        "claims": employee.expense_claims.order_by("-expense_claim_id")[:8],
    })


# ---------------------------------------------------------------------------
# Approver inbox
# ---------------------------------------------------------------------------
def inbox(request):
    if request.method == "POST":
        try:
            message = services.decide_step(request.POST["step_id"], request.POST["approver_id"],
                                           request.POST["action"], request.POST.get("comment", "").strip())
            messages.success(request, message)
        except ValueError as problem:
            messages.error(request, str(problem))
        return redirect(f"/inbox/?approver={request.POST['approver_id']}")

    approvers = Employee.objects.filter(steps_to_decide__status="PENDING").distinct().order_by("full_name")
    chosen = request.GET.get("approver") or (approvers.first().pk if approvers else "")
    steps = (ApprovalStep.objects.filter(approver_id=chosen, status="PENDING")
             .select_related("leave_request__employee", "expense_claim__employee", "approval_rule")
             .order_by("approval_step_id"))
    return render(request, "workflow/inbox.html", {"approvers": approvers, "chosen": chosen, "steps": steps})


# ---------------------------------------------------------------------------
# New request (requester): preview and submit through small JSON endpoints
# ---------------------------------------------------------------------------
def new_request(request):
    people = (Employee.objects.filter(status="ACTIVE", job_level__lte=3).exclude(special_role="FINANCE_CONTROLLER")
              .order_by("full_name"))
    return render(request, "workflow/new_request.html", {
        "people": people, "categories": ExpensePolicy.objects.order_by("category"),
        "leave_types": C.LEAVE_TYPES, "today": date.today().isoformat()})


def parse_lines(data):
    return [{"category": l["category"], "amount": float(l["amount"] or 0), "receipt_no": l.get("receipt_no", ""),
             "expense_date": date.fromisoformat(l["expense_date"])} for l in data["lines"]]


@require_POST
def api_preview(request, kind):
    """Shows what the router WOULD do. Nothing is saved."""
    try:
        data = json.loads(request.body)
        employee = get_object_or_404(Employee, pk=data["employee_id"])
        if kind == "leave":
            pv = services.leave_preview(employee, data["leave_type"], date.fromisoformat(data["start"]),
                                        date.fromisoformat(data["end"]))
            if pv["errors"]:
                return JsonResponse({"errors": pv["errors"]})
            outcome = ("Rejected at screening: " + pv["failed"][0] if pv["failed"] else "Goes to approvers")
            return JsonResponse({"errors": [], "kind": "leave", "business_days": pv["business_days"],
                                 "calendar_days": pv["calendar_days"], "available": pv["available"],
                                 "policy": pv["policy"].name, "max_days": pv["policy"].max_consecutive_days,
                                 "failed": pv["failed"], "clashes": pv["clashes"], "outcome": outcome,
                                 "plan": services.plan_view(pv["plans"])})
        pv = services.expense_preview(employee, data.get("purpose", ""), parse_lines(data))
        if pv["errors"]:
            return JsonResponse({"errors": pv["errors"]})
        return JsonResponse({"errors": [], "kind": "expense", "total": pv["total"], "worst": pv["worst"],
                             "failed": pv["failed"], "budget_exceeded": pv["budget_exceeded"],
                             "overshoot": pv["overshoot"], "cost_center": str(pv["center"]), "outcome": pv["outcome"],
                             "plan": services.plan_view(pv["plans"])})
    except (KeyError, ValueError, TypeError) as problem:
        return JsonResponse({"errors": [f"Please complete the form ({problem})"]})


@require_POST
def api_submit(request, kind):
    """Saves the request: screening, routing, approval steps and events are written to MySQL."""
    try:
        data = json.loads(request.body)
        employee = get_object_or_404(Employee, pk=data["employee_id"])
        if kind == "leave":
            new_id = services.submit_leave(employee, data["leave_type"], date.fromisoformat(data["start"]),
                                           date.fromisoformat(data["end"]), data.get("reason", ""))
            url = f"/leave/{new_id}/"
        else:
            new_id = services.submit_expense(employee, data.get("purpose", ""), parse_lines(data))
            url = f"/expenses/{new_id}/"
        return JsonResponse({"errors": [], "id": new_id, "url": url})
    except (KeyError, ValueError, TypeError) as problem:
        return JsonResponse({"errors": [str(problem)]})


# ---------------------------------------------------------------------------
# Operations analyst: exceptions and evaluation
# ---------------------------------------------------------------------------
def analyst(request):
    planted = {}
    for g in GroundTruth.objects.filter(origin="INJECTED"):
        planted.setdefault(g.issue_type, set()).add(g.entity_id)
    found = {}
    for x in DetectedException.objects.all():
        found.setdefault(x.issue_type, set()).add(x.entity_id)
    table = []
    for issue in sorted(set(planted) | set(found)):
        p, f = planted.get(issue, set()), found.get(issue, set())
        table.append({"issue": issue, "planted": len(p), "detected": len(f), "hit": len(p & f),
                      "false_alarms": len(f - p), "missed": len(p - f),
                      "recall": round(100 * len(p & f) / len(p)) if p else 100})
    issue = request.GET.get("issue", "")
    rows = DetectedException.objects.order_by("issue_type", "entity_id")
    if issue:
        rows = rows.filter(issue_type=issue)
    return render(request, "workflow/analyst.html", {
        "table": table, "page": paginate(request, rows, 20), "issue": issue,
        "issues": sorted(found),
        "leave_rejections": counts(LeaveRequest.objects.filter(status="REJECTED"), "final_reason_code"),
        "claim_rejections": counts(ExpenseClaim.objects.filter(status="REJECTED"), "final_reason_code"),
    })


# ---------------------------------------------------------------------------
# Policies and rules (reference page)
# ---------------------------------------------------------------------------
def policies(request):
    return render(request, "workflow/policies.html", {
        "rules": ApprovalRule.objects.order_by("approval_rule_id"),
        "leave_policies": LeavePolicy.objects.order_by("leave_policy_id"),
        "expense_policies": ExpensePolicy.objects.order_by("expense_policy_id"),
        "tolerance": int(round((C.POLICY_EXCEPTION_TOLERANCE - 1) * 100)),
        "overshoot": int(C.BUDGET_OVERSHOOT_LIMIT * 100),
    })
