# Rule audit and evaluation report

Produced by `python audit_rules.py`. The decisions stored in the data are re-computed from the source rows with `generator/rules.py`; a difference is acceptable only when the ground truth says it was planted.

## Acceptance checks

| Check | Unexplained issues | Result |
|---|---|---|
| Leave decisions recomputed from source rows | 0 | PASS |
| Expense decisions recomputed from source rows | 0 | PASS |
| Approver is the right person, senior enough, and not the requester | 0 | PASS |
| Reimbursements only for fully approved claims | 0 | PASS |
| No unplanned duplicate reimbursement | 0 | PASS |
| Recomputed rule labels match ground truth (labels the data should have) | 0 | PASS |
| Ground-truth rule labels are reproduced by the rules (labels the rules should give) | 0 | PASS |
| detected_exceptions.csv equals a fresh detector run | 0 | PASS |
| Every planted anomaly is detected (recall 100%) | 0 | PASS |
| Detectors raise no false alarms (precision 100%) | 0 | PASS |

## Control-failure detection (planted anomalies vs detectors)

| Issue | Planted | Detected | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|---|
| DUPLICATE_REIMBURSEMENT | 5 | 5 | 5 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| EXPENSE_OUTSIDE_EMPLOYMENT | 8 | 8 | 8 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| MISSING_COST_CENTER | 8 | 8 | 8 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| NEGATIVE_LEAVE_BALANCE | 8 | 8 | 8 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| OVERLAPPING_APPROVED_LEAVE | 5 | 5 | 5 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| SELF_APPROVAL | 6 | 6 | 6 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| SPLIT_CLAIM_EVASION | 18 | 18 | 18 | 0 | 0 | 1.0 | 1.0 | 1.0 |

## Metrics: leave

| Metric | Value |
|---|---|
| status | {'APPROVED': 659, 'REJECTED': 125, 'PENDING_APPROVAL': 16} |
| reasons | {'APPROVED_WITHIN_POLICY': 646, 'INSUFFICIENT_BALANCE': 63, 'NO_WORKING_DAYS': 39, 'OVERLAPPING_LEAVE': 22, 'APPROVED_BY_OVERRIDE': 13, 'EXCEEDS_MAX_CONSECUTIVE': 1, 'AWAITING_APPROVAL': 16} |
| approval_rate_of_decided_pct | 84.1 |
| screening_rejection_pct | 15.6 |
| average_business_days | 3.14 |
| average_days_to_approve | 2.76 |
| manager_only_pct_of_routed | 66.4 |

## Metrics: expense

| Metric | Value |
|---|---|
| status | {'REIMBURSED': 844, 'REJECTED': 125, 'APPROVED': 14, 'PENDING_APPROVAL': 17} |
| reasons | {'APPROVED_WITHIN_POLICY': 767, 'APPROVED_POLICY_EXCEPTION': 47, 'MISSING_RECEIPT': 46, 'APPROVED_BY_OVERRIDE': 16, 'POLICY_LIMIT_BREACH': 46, 'DUPLICATE_RECEIPT_HASH': 25, 'APPROVED_BUDGET_EXCEPTION': 28, 'BUDGET_EXCEEDED': 8, 'AWAITING_APPROVAL': 17} |
| approval_rate_of_decided_pct | 87.3 |
| total_submitted_usd | 1481460.5 |
| total_approved_usd | 1146160.76 |
| total_paid_usd | 1125459.62 |
| average_claim_usd | 1481.46 |
| average_days_to_approve | 3.88 |
| manager_only_pct_of_routed | 35.0 |
| three_or_more_levels_pct_of_routed | 32.9 |
| policy_exceptions_approved | 47 |
| budget_exceptions_approved | 28 |
| claims_over_budget_flag | 52 |

## Metrics: auditability

| Metric | Value |
|---|---|
| decided_requests_with_reason_code_pct | 100.0 |
| steps_with_routing_reason_pct | 100.0 |

## Metrics: rule_recomputation

| Metric | Value |
|---|---|
| leave_screened_correctly | 125 |
| leave_approved_despite_failed_screening | 13 |
| leave_paths_checked | 675 |
| claim_screened_correctly | 71 |
| claim_approved_despite_failed_screening | 16 |
| claim_paths_checked | 929 |
| self_approval_requests_found_and_explained | 6 |
