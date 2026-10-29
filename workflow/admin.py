"""Django admin = the system administrator's screen (policies, rules, employees ...)."""
from django.contrib import admin

from workflow import models

for model in [models.CostCenter, models.Employee, models.LeavePolicy, models.ExpensePolicy, models.ApprovalRule,
              models.Holiday, models.LeaveBalance, models.LeaveRequest, models.ExpenseClaim]:
    admin.site.register(model)
