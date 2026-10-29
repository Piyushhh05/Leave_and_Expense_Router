"""
models.py - one Django model per database table.

The tables are created by sql/schema.sql (not by Django migrations), so every model has
`managed = False`: Django only READS and WRITES these tables, it never creates or alters them.
Field names are the column names, so `leave_request.employee_id` is the raw ID text.
"""
from django.db import models


class Holiday(models.Model):
    holiday_id = models.CharField(max_length=8, primary_key=True)
    holiday_date = models.DateField()
    country = models.CharField(max_length=2)
    name = models.CharField(max_length=60)

    class Meta:
        managed = False
        db_table = "holidays"


class CostCenter(models.Model):
    cost_center_id = models.CharField(max_length=10, primary_key=True)
    name = models.CharField(max_length=60)
    country = models.CharField(max_length=2)
    department = models.CharField(max_length=20)
    annual_budget = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        managed = False
        db_table = "cost_centers"

    def __str__(self):
        return f"{self.cost_center_id} {self.name}"


class Employee(models.Model):
    employee_id = models.CharField(max_length=10, primary_key=True)
    full_name = models.CharField(max_length=60)
    email = models.CharField(max_length=80)
    country = models.CharField(max_length=2)
    department = models.CharField(max_length=20)
    job_level = models.IntegerField()
    job_title = models.CharField(max_length=30)
    manager = models.ForeignKey("self", models.DO_NOTHING, db_column="manager_id", null=True, blank=True,
                                related_name="reports")
    cost_center = models.ForeignKey(CostCenter, models.DO_NOTHING, db_column="cost_center_id", related_name="employees")
    hire_date = models.DateField()
    termination_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12)
    special_role = models.CharField(max_length=20, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "employees"

    def __str__(self):
        return f"{self.employee_id} {self.full_name}"


class LeavePolicy(models.Model):
    leave_policy_id = models.CharField(max_length=10, primary_key=True)
    name = models.CharField(max_length=60)
    leave_type = models.CharField(max_length=10)
    applies_to_countries = models.CharField(max_length=10)
    annual_days = models.DecimalField(max_digits=6, decimal_places=2)
    accrual_per_month = models.DecimalField(max_digits=6, decimal_places=2)
    carry_forward_cap = models.DecimalField(max_digits=6, decimal_places=2)
    max_consecutive_days = models.IntegerField()
    deducts_balance = models.BooleanField()
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "leave_policies"

    def __str__(self):
        return self.name


class LeaveBalance(models.Model):
    leave_balance_id = models.CharField(max_length=20, primary_key=True)
    employee = models.ForeignKey(Employee, models.DO_NOTHING, db_column="employee_id", related_name="balances")
    leave_policy = models.ForeignKey(LeavePolicy, models.DO_NOTHING, db_column="leave_policy_id")
    balance_year = models.IntegerField()
    opening_balance = models.DecimalField(max_digits=6, decimal_places=2)
    accrued_days = models.DecimalField(max_digits=6, decimal_places=2)
    used_days = models.DecimalField(max_digits=6, decimal_places=2)
    pending_days = models.DecimalField(max_digits=6, decimal_places=2)
    available_days = models.DecimalField(max_digits=6, decimal_places=2)
    as_of_date = models.DateField()

    class Meta:
        managed = False
        db_table = "leave_balances"


class ExpensePolicy(models.Model):
    expense_policy_id = models.CharField(max_length=10, primary_key=True)
    category = models.CharField(max_length=25)
    max_line_amount = models.DecimalField(max_digits=12, decimal_places=2)
    receipt_required_above = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "expense_policies"

    def __str__(self):
        return self.category


class ApprovalRule(models.Model):
    approval_rule_id = models.CharField(max_length=10, primary_key=True)
    domain = models.CharField(max_length=10)
    step_role = models.CharField(max_length=20)
    condition_type = models.CharField(max_length=20)
    threshold = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    match_value = models.CharField(max_length=30, null=True, blank=True)
    min_approver_level = models.IntegerField()
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    description = models.CharField(max_length=120)

    class Meta:
        managed = False
        db_table = "approval_rules"

    def __str__(self):
        return f"{self.approval_rule_id} {self.description}"


class LeaveRequest(models.Model):
    leave_request_id = models.CharField(max_length=20, primary_key=True)
    employee = models.ForeignKey(Employee, models.DO_NOTHING, db_column="employee_id", related_name="leave_requests")
    leave_policy = models.ForeignKey(LeavePolicy, models.DO_NOTHING, db_column="leave_policy_id")
    start_date = models.DateField()
    end_date = models.DateField()
    calendar_days = models.IntegerField()
    business_days = models.IntegerField()
    submitted_date = models.DateField()
    request_reason = models.CharField(max_length=80)
    balance_at_submission = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20)
    final_reason_code = models.CharField(max_length=30)
    final_decision_date = models.DateField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "leave_requests"


class ExpenseClaim(models.Model):
    expense_claim_id = models.CharField(max_length=20, primary_key=True)
    employee = models.ForeignKey(Employee, models.DO_NOTHING, db_column="employee_id", related_name="expense_claims")
    cost_center = models.ForeignKey(CostCenter, models.DO_NOTHING, db_column="cost_center_id", null=True, blank=True)
    employee_country = models.CharField(max_length=2)
    submitted_date = models.DateField()
    purpose = models.CharField(max_length=80)
    currency = models.CharField(max_length=3)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    line_count = models.IntegerField()
    has_policy_breach = models.BooleanField()
    budget_exceeded = models.BooleanField()
    status = models.CharField(max_length=20)
    final_reason_code = models.CharField(max_length=30)
    final_decision_date = models.DateField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "expense_claims"


class ExpenseLine(models.Model):
    expense_line_id = models.CharField(max_length=40, primary_key=True)
    expense_claim = models.ForeignKey(ExpenseClaim, models.DO_NOTHING, db_column="expense_claim_id", related_name="lines")
    line_no = models.IntegerField()
    expense_policy = models.ForeignKey(ExpensePolicy, models.DO_NOTHING, db_column="expense_policy_id")
    expense_date = models.DateField()
    merchant = models.CharField(max_length=60)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    receipt_provided = models.BooleanField()
    receipt_file_name = models.CharField(max_length=40, null=True, blank=True)
    receipt_hash = models.CharField(max_length=16, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "expense_lines"
        ordering = ["line_no"]


class ApprovalStep(models.Model):
    approval_step_id = models.CharField(max_length=40, primary_key=True)
    leave_request = models.ForeignKey(LeaveRequest, models.DO_NOTHING, db_column="leave_request_id", null=True,
                                      blank=True, related_name="steps")
    expense_claim = models.ForeignKey(ExpenseClaim, models.DO_NOTHING, db_column="expense_claim_id", null=True,
                                      blank=True, related_name="steps")
    step_no = models.IntegerField()
    approval_rule = models.ForeignKey(ApprovalRule, models.DO_NOTHING, db_column="approval_rule_id")
    approver_role = models.CharField(max_length=20)
    approver = models.ForeignKey(Employee, models.DO_NOTHING, db_column="approver_id", related_name="steps_to_decide")
    status = models.CharField(max_length=10)
    decided_date = models.DateField(null=True, blank=True)
    routing_reason = models.CharField(max_length=200)
    decision_reason_code = models.CharField(max_length=30, null=True, blank=True)
    decision_reason = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "approval_steps"
        ordering = ["step_no"]

    @property
    def request(self):
        return self.leave_request or self.expense_claim


class Reimbursement(models.Model):
    reimbursement_id = models.CharField(max_length=20, primary_key=True)
    expense_claim = models.ForeignKey(ExpenseClaim, models.DO_NOTHING, db_column="expense_claim_id",
                                      related_name="reimbursements")
    employee = models.ForeignKey(Employee, models.DO_NOTHING, db_column="employee_id", related_name="reimbursements")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    payment_method = models.CharField(max_length=15)
    approved_date = models.DateField()
    payment_date = models.DateField()
    status = models.CharField(max_length=10)

    class Meta:
        managed = False
        db_table = "reimbursements"


class StatusEvent(models.Model):
    event_id = models.CharField(max_length=10, primary_key=True)
    leave_request = models.ForeignKey(LeaveRequest, models.DO_NOTHING, db_column="leave_request_id", null=True,
                                      blank=True, related_name="events")
    expense_claim = models.ForeignKey(ExpenseClaim, models.DO_NOTHING, db_column="expense_claim_id", null=True,
                                      blank=True, related_name="events")
    from_status = models.CharField(max_length=20, null=True, blank=True)
    to_status = models.CharField(max_length=20)
    event_date = models.DateField()
    actor_type = models.CharField(max_length=10)
    actor = models.ForeignKey(Employee, models.DO_NOTHING, db_column="actor_id", null=True, blank=True,
                              related_name="events")
    reason_code = models.CharField(max_length=30)
    note = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "status_events"
        ordering = ["event_id"]


class GroundTruth(models.Model):
    """The answer key. Only the evaluation page reads it - never the decision logic."""
    ground_truth_id = models.CharField(max_length=10, primary_key=True)
    entity_type = models.CharField(max_length=20)
    entity_id = models.CharField(max_length=40)
    issue_type = models.CharField(max_length=30)
    origin = models.CharField(max_length=15)
    expected_decision = models.CharField(max_length=40)
    group_id = models.CharField(max_length=20, null=True, blank=True)
    notes = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "ground_truth"


class DetectedException(models.Model):
    detection_id = models.CharField(max_length=10, primary_key=True)
    entity_type = models.CharField(max_length=20)
    entity_id = models.CharField(max_length=40)
    issue_type = models.CharField(max_length=30)
    detail = models.CharField(max_length=200)

    class Meta:
        managed = False
        db_table = "detected_exceptions"
