"""Two tiny template filters: coloured status badges and readable codes."""
from django import template

register = template.Library()

COLORS = {
    "APPROVED": "success", "REIMBURSED": "success", "PAID": "success",
    "PENDING_APPROVAL": "warning", "PENDING": "warning", "SCHEDULED": "info", "SUBMITTED": "secondary",
    "WAITING": "secondary", "SKIPPED": "light text-dark border", "REJECTED": "danger",
}


@register.filter
def badge(status):
    """APPROVED -> 'success' (a Bootstrap colour name)."""
    return COLORS.get(status, "secondary")


@register.filter
def pretty(code):
    """APPROVED_WITHIN_POLICY -> 'Approved within policy'."""
    return str(code).replace("_", " ").capitalize() if code else ""
