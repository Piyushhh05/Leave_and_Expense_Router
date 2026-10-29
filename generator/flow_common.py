"""
flow_common.py - pieces shared by the leave flow and the expense flow:
building the approval plan, the approval_steps rows and the status_events rows.
"""
from generator import rules
from generator.helpers import step_id


def build_plans(domain, facts, ctx, requester, submitted, decide):
    """
    One 'plan' per required approver role.
      * the approver is resolved from the hierarchy,
      * if the same person already appears in an earlier step, that step is SKIPPED
        (one person never approves the same request twice),
      * decide(role) gives the planned decision (status, code, text).
    """
    plans = []
    required = rules.required_steps(domain, facts, ctx["rules"], submitted)
    for role, rule in required:
        approver = rules.resolve_approver(role, requester, ctx["emp"], ctx["holders"])
        same_as = None
        for earlier_index, earlier in enumerate(plans):
            if earlier["approver_id"] == approver:
                same_as = earlier_index
                break
        status, code, text = decide(role)
        plans.append({
            "role": role, "rule": rule, "approver_id": approver, "same_as": same_as,
            "routing_text": rules.routing_text(rule, domain, facts),
            "planned_status": status, "planned_code": code, "planned_text": text,
        })
    return plans


def step_rows(kind, entity_id, plans):
    """Turns plans (after walk_steps) into approval_steps rows. kind is 'leave' or 'expense'."""
    rows = []
    for number, plan in enumerate(plans, start=1):
        rows.append({
            "approval_step_id": step_id(entity_id, number),
            "leave_request_id": entity_id if kind == "leave" else None,
            "expense_claim_id": entity_id if kind == "expense" else None,
            "step_no": number,
            "approval_rule_id": plan["rule"]["approval_rule_id"],
            "approver_role": plan["role"],
            "approver_id": plan["approver_id"],
            "status": plan["status"],
            "decided_date": plan["decided_date"],
            "routing_reason": plan["routing_text"],
            "decision_reason_code": plan["code"],
            "decision_reason": plan["text"],
        })
    return rows


def status_events(kind, entity_id, requester_id, submitted, plans, status, final_date,
                  final_code, screening_code, screening_note):
    """
    The history of status changes (never overwritten, only appended):
      SUBMITTED -> REJECTED                (screening failed)      or
      SUBMITTED -> PENDING_APPROVAL -> APPROVED / REJECTED
    Returns a list of event dictionaries (event ids are assigned later, globally).
    """
    key = "leave_request_id" if kind == "leave" else "expense_claim_id"

    def event(order, old, new, day, actor_type, actor_id, code, note):
        return {key: entity_id, "order": order, "from_status": old, "to_status": new,
                "event_date": day, "actor_type": actor_type, "actor_id": actor_id,
                "reason_code": code, "note": note}

    events = [event(1, None, "SUBMITTED", submitted, "EMPLOYEE", requester_id, "AWAITING_APPROVAL", "Request submitted")]
    if screening_code:
        events.append(event(2, "SUBMITTED", "REJECTED", submitted, "SYSTEM", None, screening_code, screening_note))
        return events
    path = " > ".join(p["role"] for p in plans)
    events.append(event(2, "SUBMITTED", "PENDING_APPROVAL", submitted, "SYSTEM", None,
                        "AWAITING_APPROVAL", "Routed to: " + path))
    if status in ("APPROVED", "REJECTED"):
        deciding = [p for p in plans if p["decided_date"] is not None][-1]
        events.append(event(3, "PENDING_APPROVAL", status, final_date, "EMPLOYEE",
                            deciding["approver_id"], final_code, deciding["text"]))
    return events
