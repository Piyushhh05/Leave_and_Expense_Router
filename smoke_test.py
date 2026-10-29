"""
smoke_test.py - checks that every page opens and that the workflow works end to end.

    python smoke_test.py          (needs the database loaded: python manage.py load_data)

Everything it writes is rolled back at the end, so the database is left as it was.
"""
import json
import os
import sys
from datetime import date

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.test.utils import setup_test_environment  # noqa: E402

setup_test_environment()     # lets the test client report template context (flash messages)

from django.db import transaction  # noqa: E402
from django.test import Client  # noqa: E402

from workflow.models import (ApprovalStep, Employee, ExpenseClaim, LeaveBalance, LeaveRequest, Reimbursement,  # noqa: E402
                             StatusEvent)

client = Client(HTTP_HOST="localhost")
passed, failed = [], []


def check(name, condition, detail=""):
    (passed if condition else failed).append(name)
    print(("PASS  " if condition else "FAIL  ") + name + ("" if condition else f"   {detail}"))


def post_json(url, payload):
    return client.post(url, json.dumps(payload), content_type="application/json").json()


def approve_all(request_obj, kind):
    """Approves every step in turn using the real inbox form. Returns the list of messages."""
    messages = []
    for _ in range(10):
        step = ApprovalStep.objects.filter(**{("leave_request" if kind == "leave" else "expense_claim"): request_obj,
                                              "status": "PENDING"}).first()
        if step is None:
            break
        response = client.post("/inbox/", {"step_id": step.pk, "approver_id": step.approver_id,
                                           "action": "APPROVE", "comment": "ok"}, follow=True)
        messages.extend(str(m) for m in response.context["messages"])
    return messages


def main():
    # ---- 1. every page opens
    leave = LeaveRequest.objects.order_by("leave_request_id").first()
    claim = ExpenseClaim.objects.order_by("expense_claim_id").first()
    emp = Employee.objects.get(pk="EMP-000100")
    for url in ["/", "/leave/", f"/leave/{leave.pk}/", "/expenses/", f"/expenses/{claim.pk}/", "/employees/",
                f"/employees/{emp.pk}/", "/inbox/", "/new/", "/analyst/", "/analyst/?issue=SELF_APPROVAL", "/policies/",
                "/leave/?status=REJECTED&reason=INSUFFICIENT_BALANCE", "/expenses/?q=Aarav", "/admin/login/"]:
        status = client.get(url).status_code
        check(f"GET {url} -> {status}", status == 200)
    check("every leave detail page opens (sampled 60)",
          all(client.get(f"/leave/{pk}/").status_code == 200 for pk in LeaveRequest.objects.values_list("pk", flat=True)[:60]))
    check("every expense detail page opens (sampled 60)",
          all(client.get(f"/expenses/{pk}/").status_code == 200 for pk in ExpenseClaim.objects.values_list("pk", flat=True)[:60]))

    with transaction.atomic():
        # pick an active associate with a manager and a skip-level manager
        requester = Employee.objects.filter(status="ACTIVE", job_level=1, country="IN", special_role=None).first()

        # ---- 2. leave: preview, submit, approve through the whole chain
        payload = {"employee_id": requester.pk, "leave_type": "ANNUAL", "start": "2026-12-01", "end": "2026-12-04",
                   "reason": "smoke test"}
        pv = post_json("/api/preview/leave/", payload)
        check("leave preview: 4 business days, manager + skip-manager route",
              pv["business_days"] == 4 and [s["role"] for s in pv["plan"]] == ["MANAGER", "SKIP_MANAGER"], str(pv))
        bal_before = LeaveBalance.objects.get(employee=requester, leave_policy_id="LPOL-01")
        events_before = StatusEvent.objects.count()
        sub = post_json("/api/submit/leave/", payload)
        new_leave = LeaveRequest.objects.get(pk=sub["id"])
        check("leave submit: PENDING_APPROVAL with 2 steps", new_leave.status == "PENDING_APPROVAL" and new_leave.steps.count() == 2)
        check("leave submit: first step PENDING, second WAITING",
              [s.status for s in new_leave.steps.order_by("step_no")] == ["PENDING", "WAITING"])
        bal_mid = LeaveBalance.objects.get(pk=bal_before.pk)
        check("balance: 4 days become pending", bal_mid.pending_days == bal_before.pending_days + 4
              and bal_mid.available_days == bal_before.available_days - 4)
        messages = approve_all(new_leave, "leave")
        new_leave.refresh_from_db()
        check("leave: approved after last step", new_leave.status == "APPROVED" and new_leave.final_reason_code == "APPROVED_WITHIN_POLICY", str(messages))
        bal_after = LeaveBalance.objects.get(pk=bal_before.pk)
        check("balance: pending moved to used, available unchanged",
              bal_after.used_days == bal_before.used_days + 4 and bal_after.pending_days == bal_before.pending_days
              and bal_after.available_days == bal_before.available_days - 4)
        check("history appended (3 events: submitted, routed to approvers, approved)", StatusEvent.objects.count() - events_before == 3)

        # insufficient balance -> rejected at screening, nothing to approve
        big = post_json("/api/submit/leave/", {**payload, "start": "2027-01-04", "end": "2027-02-26"})
        rejected = LeaveRequest.objects.get(pk=big["id"])
        check("leave over balance / max days is rejected at screening with no steps",
              rejected.status == "REJECTED" and rejected.steps.count() == 0, rejected.final_reason_code)

        # overlapping the request we just approved
        overlap = post_json("/api/submit/leave/", {**payload, "start": "2026-12-03", "end": "2026-12-03"})
        check("overlapping leave is rejected", LeaveRequest.objects.get(pk=overlap["id"]).final_reason_code == "OVERLAPPING_LEAVE")

        # ---- 3. expense: within policy, multi level, reimbursement only after the last approval
        base_lines = [{"category": "TRAVEL", "amount": 700, "expense_date": "2026-10-20", "receipt_no": "SMOKE-R1"},
                      {"category": "LODGING", "amount": 300, "expense_date": "2026-10-21", "receipt_no": "SMOKE-R2"}]
        epay = {"employee_id": requester.pk, "purpose": "smoke test", "lines": base_lines}
        pv = post_json("/api/preview/expense/", epay)
        check("expense preview: 1000 USD -> manager + skip-manager", [s["role"] for s in pv["plan"]][:2] == ["MANAGER", "SKIP_MANAGER"], str(pv))
        sub = post_json("/api/submit/expense/", epay)
        new_claim = ExpenseClaim.objects.get(pk=sub["id"])
        check("expense submit: pending, no reimbursement yet",
              new_claim.status == "PENDING_APPROVAL" and not Reimbursement.objects.filter(expense_claim=new_claim).exists())
        approve_all(new_claim, "expense")
        new_claim.refresh_from_db()
        pay = Reimbursement.objects.filter(expense_claim=new_claim)
        check("expense approved -> exactly one SCHEDULED reimbursement for the claim total",
              new_claim.status == "APPROVED" and pay.count() == 1 and pay[0].status == "SCHEDULED"
              and pay[0].amount == new_claim.total_amount, f"{new_claim.status} {pay.count()}")

        # duplicate receipt number -> screening rejection
        dup = post_json("/api/submit/expense/", epay)
        check("duplicate receipt is rejected at screening",
              ExpenseClaim.objects.get(pk=dup["id"]).final_reason_code == "DUPLICATE_RECEIPT_HASH")

        # missing receipt for a line that needs one
        nor = post_json("/api/submit/expense/", {**epay, "lines": [{"category": "TRAVEL", "amount": 80,
                                                                       "expense_date": "2026-10-20", "receipt_no": ""}]})
        check("missing receipt is rejected at screening",
              ExpenseClaim.objects.get(pk=nor["id"]).final_reason_code == "MISSING_RECEIPT")

        # policy breach: up to 120% goes to finance as an exception, beyond 120% is rejected by finance
        tol = post_json("/api/preview/expense/", {**epay, "lines": [{"category": "MEALS", "amount": 110,
                                                                       "expense_date": "2026-10-20", "receipt_no": "T1"}]})
        check("meal 110 vs limit 100 -> finance controller step, exception expected",
              "FINANCE_CONTROLLER" in [s["role"] for s in tol["plan"]] and "APPROVED" in tol["outcome"], str(tol))
        beyond = post_json("/api/preview/expense/", {**epay, "lines": [{"category": "MEALS", "amount": 130,
                                                                          "expense_date": "2026-10-20", "receipt_no": "T2"}]})
        check("meal 130 vs limit 100 -> predicted rejection by finance controller", "REJECTED at FINANCE_CONTROLLER" in beyond["outcome"], str(beyond))

        # ---- 4. guards in the inbox
        sub = post_json("/api/submit/expense/", {**epay, "lines": [{"category": "MEALS", "amount": 130, "expense_date": "2026-10-20", "receipt_no": "T3"}]})
        blocked_claim = ExpenseClaim.objects.get(pk=sub["id"])
        step = blocked_claim.steps.order_by("step_no").first()
        # wrong approver
        other = Employee.objects.exclude(pk=step.approver_id).first()
        resp = client.post("/inbox/", {"step_id": step.pk, "approver_id": other.pk, "action": "APPROVE"}, follow=True)
        check("someone else cannot decide my step", "assigned to someone else" in " ".join(str(m) for m in resp.context["messages"]))
        # requester cannot approve own request: make the requester the approver of the pending step
        ApprovalStep.objects.filter(pk=step.pk).update(approver_id=requester.pk)
        resp = client.post("/inbox/", {"step_id": step.pk, "approver_id": requester.pk, "action": "APPROVE"}, follow=True)
        check("requester cannot approve own request", "own request" in " ".join(str(m) for m in resp.context["messages"]))
        ApprovalStep.objects.filter(pk=step.pk).update(approver_id=step.approver_id)
        # rejection skips the remaining steps and finishes the claim; no reimbursement
        resp = client.post("/inbox/", {"step_id": step.pk, "approver_id": step.approver_id, "action": "REJECT", "comment": "no"}, follow=True)
        blocked_claim.refresh_from_db()
        check("manager rejection finishes the claim, later steps skipped, no payment",
              blocked_claim.status == "REJECTED" and not blocked_claim.reimbursements.exists()
              and all(s.status in ("REJECTED", "SKIPPED") for s in blocked_claim.steps.all()))
        # approving a step twice
        resp = client.post("/inbox/", {"step_id": step.pk, "approver_id": step.approver_id, "action": "APPROVE"}, follow=True)
        check("a decided step cannot be decided again", "not waiting" in " ".join(str(m) for m in resp.context["messages"]))

        transaction.set_rollback(True)          # throw away everything written above

    check("rollback left the database unchanged", not LeaveRequest.objects.filter(request_reason="smoke test").exists())
    print(f"\n{len(passed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
