# Validation summary

Produced by `python validate_data.py`. Structural checks only; business rules are in `audit_report.md`.

| # | Check | Result |
|---|---|---|
| 1 | holidays: columns match the data dictionary | PASS |
| 2 | holidays: required / type / enum / pattern | PASS |
| 3 | holidays: primary key holiday_id unique | PASS |
| 4 | holidays: unique columns | PASS |
| 5 | holidays: foreign keys exist | PASS |
| 6 | cost_centers: columns match the data dictionary | PASS |
| 7 | cost_centers: required / type / enum / pattern | PASS |
| 8 | cost_centers: primary key cost_center_id unique | PASS |
| 9 | cost_centers: unique columns | PASS |
| 10 | cost_centers: foreign keys exist | PASS |
| 11 | employees: columns match the data dictionary | PASS |
| 12 | employees: required / type / enum / pattern | PASS |
| 13 | employees: primary key employee_id unique | PASS |
| 14 | employees: unique columns | PASS |
| 15 | employees: foreign keys exist | PASS |
| 16 | leave_policies: columns match the data dictionary | PASS |
| 17 | leave_policies: required / type / enum / pattern | PASS |
| 18 | leave_policies: primary key leave_policy_id unique | PASS |
| 19 | leave_policies: unique columns | PASS |
| 20 | leave_policies: foreign keys exist | PASS |
| 21 | leave_balances: columns match the data dictionary | PASS |
| 22 | leave_balances: required / type / enum / pattern | PASS |
| 23 | leave_balances: primary key leave_balance_id unique | PASS |
| 24 | leave_balances: unique columns | PASS |
| 25 | leave_balances: foreign keys exist | PASS |
| 26 | expense_policies: columns match the data dictionary | PASS |
| 27 | expense_policies: required / type / enum / pattern | PASS |
| 28 | expense_policies: primary key expense_policy_id unique | PASS |
| 29 | expense_policies: unique columns | PASS |
| 30 | expense_policies: foreign keys exist | PASS |
| 31 | approval_rules: columns match the data dictionary | PASS |
| 32 | approval_rules: required / type / enum / pattern | PASS |
| 33 | approval_rules: primary key approval_rule_id unique | PASS |
| 34 | approval_rules: unique columns | PASS |
| 35 | approval_rules: foreign keys exist | PASS |
| 36 | leave_requests: columns match the data dictionary | PASS |
| 37 | leave_requests: required / type / enum / pattern | PASS |
| 38 | leave_requests: primary key leave_request_id unique | PASS |
| 39 | leave_requests: unique columns | PASS |
| 40 | leave_requests: foreign keys exist | PASS |
| 41 | expense_claims: columns match the data dictionary | PASS |
| 42 | expense_claims: required / type / enum / pattern | PASS |
| 43 | expense_claims: primary key expense_claim_id unique | PASS |
| 44 | expense_claims: unique columns | PASS |
| 45 | expense_claims: foreign keys exist | PASS |
| 46 | expense_lines: columns match the data dictionary | PASS |
| 47 | expense_lines: required / type / enum / pattern | PASS |
| 48 | expense_lines: primary key expense_line_id unique | PASS |
| 49 | expense_lines: unique columns | PASS |
| 50 | expense_lines: foreign keys exist | PASS |
| 51 | approval_steps: columns match the data dictionary | PASS |
| 52 | approval_steps: required / type / enum / pattern | PASS |
| 53 | approval_steps: primary key approval_step_id unique | PASS |
| 54 | approval_steps: unique columns | PASS |
| 55 | approval_steps: foreign keys exist | PASS |
| 56 | approval_steps: exactly one of leave_request_id / expense_claim_id | PASS |
| 57 | reimbursements: columns match the data dictionary | PASS |
| 58 | reimbursements: required / type / enum / pattern | PASS |
| 59 | reimbursements: primary key reimbursement_id unique | PASS |
| 60 | reimbursements: unique columns | PASS |
| 61 | reimbursements: foreign keys exist | PASS |
| 62 | status_events: columns match the data dictionary | PASS |
| 63 | status_events: required / type / enum / pattern | PASS |
| 64 | status_events: primary key event_id unique | PASS |
| 65 | status_events: unique columns | PASS |
| 66 | status_events: foreign keys exist | PASS |
| 67 | status_events: exactly one of leave_request_id / expense_claim_id | PASS |
| 68 | ground_truth: columns match the data dictionary | PASS |
| 69 | ground_truth: required / type / enum / pattern | PASS |
| 70 | ground_truth: primary key ground_truth_id unique | PASS |
| 71 | ground_truth: unique columns | PASS |
| 72 | ground_truth: foreign keys exist | PASS |
| 73 | employees: hierarchy, status and dates | PASS |
| 74 | employees: exactly one holder per special role | PASS |
| 75 | cost_centers: budget = headcount x per-head amount | PASS |
| 76 | leave_requests: date ordering and employment window | PASS |
| 77 | leave_requests: calendar and business days recomputed (weekends + holidays) | PASS |
| 78 | leave_requests: policy applies to the employee's country | PASS |
| 79 | leave_balances: opening + accrued - used - pending = available (and accrual formula) | PASS |
| 80 | expense_claims: total = sum of lines | PASS |
| 81 | expense_claims: line count 1-10, numbering, breach flag, country | PASS |
| 82 | expense_claims / lines: date ordering | PASS |
| 83 | expense_lines: receipt metadata consistent; id format | PASS |
| 84 | approval_steps: numbering and id format | PASS |
| 85 | approval_steps: lifecycle (decided -> pending -> waiting, rejection skips the rest) | PASS |
| 86 | approval_steps: decision dates | PASS |
| 87 | reimbursements: only for approved claims; amounts, dates and status reconcile | PASS |
| 88 | status_events: legal transitions, history ends at the current status | PASS |
| 89 | ID counters are zero padded and gap free | PASS |
| 90 | ground_truth: every label points to a real record | PASS |
| 91 | ground_truth: no label columns inside input tables | PASS |

**91 of 91 checks passed.**

## Row counts

- holidays: 25
- cost_centers: 25
- employees: 400
- leave_policies: 6
- leave_balances: 1200
- expense_policies: 8
- approval_rules: 12
- leave_requests: 800
- expense_claims: 1000
- expense_lines: 3121
- approval_steps: 2815
- reimbursements: 863
- status_events: 6015
- ground_truth: 1034
