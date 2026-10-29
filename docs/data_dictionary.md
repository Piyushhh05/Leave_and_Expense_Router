# Data dictionary

Generated from `generator/schema_spec.py` (`python -m generator.schema_spec`). The validator enforces exactly what is written here.

Money is always **USD** (one reporting currency, no FX). Leave quantities are in **days**.

## Relationships and cardinality

| Parent | Child | Cardinality | Key | Note |
|---|---|---|---|---|
| employees | employees | 1:N, optional | `manager_id` | A manager has many reports. The CEO has no manager. |
| cost_centers | employees | 1:N | `cost_center_id` | An employee is charged to one cost centre. |
| employees | leave_policies | N:M via leave_balances | `employee_id + leave_policy_id` | One balance row per employee, policy and year. |
| employees | leave_requests | 1:N | `employee_id` | One employee raises many requests. |
| leave_policies | leave_requests | 1:N | `leave_policy_id` | Each request is of one leave type/policy. |
| employees | expense_claims | 1:N | `employee_id` | One employee raises many claims. |
| cost_centers | expense_claims | 1:N, optional | `cost_center_id` | Optional in the table so the missing-cost-centre anomaly can be stored and labelled. |
| expense_claims | expense_lines | 1:N (1 to 10) | `expense_claim_id` | A claim has 1 to 10 lines. |
| expense_policies | expense_lines | 1:N | `expense_policy_id` | Each line is governed by its category policy. |
| leave_requests / expense_claims | approval_steps | 1:N (one of two, optional each) | `leave_request_id / expense_claim_id` | Steps belong to exactly one request. |
| approval_rules | approval_steps | 1:N  (so requests <-> rules is N:M via approval_steps) | `approval_rule_id` | Which rule produced the step. |
| employees | approval_steps | 1:N | `approver_id` | The person who must decide the step. |
| expense_claims | reimbursements | 1:0..1 (1:N only for the duplicate-reimbursement anomaly) | `expense_claim_id` | Created only after final approval. |
| leave_requests / expense_claims | status_events | 1:N | `leave_request_id / expense_claim_id` | Append-only status history. |

## Lifecycle states

- **Leave request**: (none) -> SUBMITTED -> PENDING_APPROVAL -> APPROVED | REJECTED.  SUBMITTED -> REJECTED is a system screening rejection.
- **Expense claim**: (none) -> SUBMITTED -> PENDING_APPROVAL -> APPROVED -> REIMBURSED.  Also SUBMITTED -> REJECTED (screening) and PENDING_APPROVAL -> REJECTED.
- **Approval step**: WAITING -> PENDING -> APPROVED | REJECTED.  Steps after a rejection become SKIPPED.
- **Reimbursement**: SCHEDULED -> PAID (by payment_date).

## holidays

Illustrative public holidays per country (used for business-day counts).

Primary key: `holiday_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `holiday_id` | str:8 | yes | pattern `^HOL-\d{3}$` |  | yes | HOL-001, HOL-002 ... |
| `holiday_date` | date | yes |  |  |  | Must fall inside the balance year |
| `country` | str:2 | yes | IN, US, UK, DE |  |  |  |
| `name` | str:60 | yes |  |  |  |  |

## cost_centers

Budget owners. Employees and expense claims are charged to a cost centre.

Primary key: `cost_center_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `cost_center_id` | str:10 | yes | pattern `^CC-\d{3}$` |  | yes |  |
| `name` | str:60 | yes |  |  |  |  |
| `country` | str:2 | yes | IN, US, UK, DE |  |  |  |
| `department` | str:20 | yes | Engineering, Sales, Finance, HR, Operations, Marketing, Executive |  |  |  |
| `annual_budget` | dec:12,2 | yes |  | USD |  | > 0; = headcount x BUDGET_PER_HEAD |

## employees

Employee master with the reporting hierarchy (manager_id points to another employee).

Primary key: `employee_id`

Foreign keys: `manager_id` -> `employees.employee_id`, `cost_center_id` -> `cost_centers.cost_center_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `employee_id` | str:10 | yes | pattern `^EMP-\d{6}$` |  | yes |  |
| `full_name` | str:60 | yes |  |  |  |  |
| `email` | str:80 | yes |  |  | yes | Unique; uses the reserved example.com domain |
| `country` | str:2 | yes | IN, US, UK, DE |  |  |  |
| `department` | str:20 | yes | Engineering, Sales, Finance, HR, Operations, Marketing, Executive |  |  |  |
| `job_level` | int | yes | 1, 2, 3, 4, 5 |  |  | 1 Associate, 2 Manager, 3 Director, 4 VP, 5 CEO |
| `job_title` | str:30 | yes |  |  |  |  |
| `manager_id` | str:10 | no |  |  |  | Empty only for the CEO; manager must have a higher job_level |
| `cost_center_id` | str:10 | yes |  |  |  |  |
| `hire_date` | date | yes |  |  |  | Not after the dataset as-of date |
| `termination_date` | date | no |  |  |  | Empty for ACTIVE; >= hire_date for TERMINATED |
| `status` | str:12 | yes | ACTIVE, TERMINATED |  |  |  |
| `special_role` | str:20 | no | FINANCE_CONTROLLER, CFO, HR_HEAD |  |  | Designated approver roles. Exactly one employee per role |

## leave_policies

Six leave policies. LPOL-03 covers both UK and DE (see applies_to_countries).

Primary key: `leave_policy_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `leave_policy_id` | str:10 | yes | pattern `^LPOL-\d{2}$` |  | yes |  |
| `name` | str:60 | yes |  |  |  |  |
| `leave_type` | str:10 | yes | ANNUAL, SICK, CASUAL, UNPAID |  |  |  |
| `applies_to_countries` | str:10 | yes |  |  |  | ALL, one country code, or codes joined by \| |
| `annual_days` | dec:6,2 | yes |  | days |  | >= 0 |
| `accrual_per_month` | dec:6,2 | yes |  | days |  | >= 0; annual_days / 12 or close |
| `carry_forward_cap` | dec:6,2 | yes |  | days |  | >= 0 |
| `max_consecutive_days` | int | yes |  | business days |  | > 0 |
| `deducts_balance` | bool | yes |  |  |  | 0 for unpaid leave (no balance check) |
| `effective_from` | date | yes |  |  |  |  |
| `effective_to` | date | no |  |  |  | Empty = still in force |

## leave_balances

BRIDGE table between employees and leave policies (N:M) holding one balance per year.

Primary key: `leave_balance_id`

Foreign keys: `employee_id` -> `employees.employee_id`, `leave_policy_id` -> `leave_policies.leave_policy_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `leave_balance_id` | str:20 | yes | pattern `^LBAL-\d{4}-\d{6}$` |  | yes |  |
| `employee_id` | str:10 | yes |  |  |  |  |
| `leave_policy_id` | str:10 | yes |  |  |  |  |
| `balance_year` | int | yes |  |  |  | = 2026 |
| `opening_balance` | dec:6,2 | yes |  | days |  | Carry forward, 0 <= x <= carry_forward_cap |
| `accrued_days` | dec:6,2 | yes |  | days |  | = min(annual_days, accrual_per_month x months accrued) |
| `used_days` | dec:6,2 | yes |  | days |  | = sum of business_days of APPROVED requests |
| `pending_days` | dec:6,2 | yes |  | days |  | = sum of business_days of PENDING_APPROVAL requests |
| `available_days` | dec:6,2 | yes |  | days |  | = opening + accrued - used - pending (negative = anomaly) |
| `as_of_date` | date | yes |  |  |  | Date the balance was calculated |

## expense_policies

One expense policy per category: per-line limit and receipt rule.

Primary key: `expense_policy_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `expense_policy_id` | str:10 | yes | pattern `^EPOL-\d{2}$` |  | yes |  |
| `category` | str:25 | yes | MEALS, TRAVEL, LODGING, SUPPLIES, TRAINING, CLIENT_ENTERTAINMENT, SOFTWARE, EQUIPMENT |  | yes |  |
| `max_line_amount` | dec:12,2 | yes |  | USD |  | > 0; a line above this is a policy limit breach |
| `receipt_required_above` | dec:12,2 | yes |  | USD |  | >= 0; lines above this need a receipt |
| `effective_from` | date | yes |  |  |  |  |
| `effective_to` | date | no |  |  |  |  |

## approval_rules

Routing rules (data, not code). The router reads these to decide who must approve.

Primary key: `approval_rule_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `approval_rule_id` | str:10 | yes | pattern `^APRL-[LE]\d$` |  | yes |  |
| `domain` | str:10 | yes | LEAVE, EXPENSE |  |  |  |
| `step_role` | str:20 | yes | MANAGER, SKIP_MANAGER, HR_HEAD, FINANCE_CONTROLLER, CFO |  |  |  |
| `condition_type` | str:20 | yes | ALWAYS, DAYS_ABOVE, LEAVE_TYPE, AMOUNT_ABOVE, CATEGORY, COUNTRY_AMOUNT, POLICY_BREACH, BUDGET_EXCEEDED |  |  |  |
| `threshold` | dec:12,2 | no |  |  |  | Days or USD depending on condition_type |
| `match_value` | str:30 | no |  |  |  | Leave type, category or countries joined by \| |
| `min_approver_level` | int | yes | 2, 3, 4 |  |  | Approver's job_level must be at least this |
| `effective_from` | date | yes |  |  |  |  |
| `effective_to` | date | no |  |  |  |  |
| `description` | str:120 | yes |  |  |  |  |

## leave_requests

A request for time off. Status changes are NOT overwritten silently: see status_events.

Primary key: `leave_request_id`

Foreign keys: `employee_id` -> `employees.employee_id`, `leave_policy_id` -> `leave_policies.leave_policy_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `leave_request_id` | str:20 | yes | pattern `^LVE-\d{4}-\d{6}$` |  | yes |  |
| `employee_id` | str:10 | yes |  |  |  |  |
| `leave_policy_id` | str:10 | yes |  |  |  |  |
| `start_date` | date | yes |  |  |  |  |
| `end_date` | date | yes |  |  |  | >= start_date |
| `calendar_days` | int | yes |  | days |  | = end_date - start_date + 1 |
| `business_days` | int | yes |  | days |  | Weekdays in range minus country public holidays |
| `submitted_date` | date | yes |  |  |  | <= start_date |
| `request_reason` | str:80 | yes |  |  |  |  |
| `balance_at_submission` | dec:6,2 | no |  | days |  | Available balance when submitted. Empty for unpaid leave |
| `status` | str:20 | yes | SUBMITTED, PENDING_APPROVAL, APPROVED, REJECTED |  |  |  |
| `final_reason_code` | str:30 | yes | AWAITING_APPROVAL, APPROVED_WITHIN_POLICY, APPROVED_BY_OVERRIDE, NO_WORKING_DAYS, OVERLAPPING_LEAVE, INSUFFICIENT_BALANCE, EXCEEDS_MAX_CONSECUTIVE, REJECTED_BY_APPROVER |  |  |  |
| `final_decision_date` | date | no |  |  |  | Empty while pending |

## expense_claims

Header of an expense claim. total_amount and line_count are derived from expense_lines.

Primary key: `expense_claim_id`

Foreign keys: `employee_id` -> `employees.employee_id`, `cost_center_id` -> `cost_centers.cost_center_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `expense_claim_id` | str:20 | yes | pattern `^EXP-\d{4}-\d{6}$` |  | yes |  |
| `employee_id` | str:10 | yes |  |  |  |  |
| `cost_center_id` | str:10 | no |  |  |  | Required by policy. Empty = anomaly MISSING_COST_CENTER |
| `employee_country` | str:2 | yes | IN, US, UK, DE |  |  | Country of the employee when submitted (used for routing) |
| `submitted_date` | date | yes |  |  |  |  |
| `purpose` | str:80 | yes |  |  |  |  |
| `currency` | str:3 | yes | USD |  |  | Single reporting currency, no FX |
| `total_amount` | dec:12,2 | yes |  | USD |  | = sum of line amounts |
| `line_count` | int | yes |  |  |  | = number of lines, 1 to 10 |
| `has_policy_breach` | bool | yes |  |  |  | 1 if any line is above its policy limit |
| `budget_exceeded` | bool | yes |  |  |  | 1 if approving would push the cost centre over budget |
| `status` | str:20 | yes | SUBMITTED, PENDING_APPROVAL, APPROVED, REJECTED, REIMBURSED |  |  |  |
| `final_reason_code` | str:30 | yes | AWAITING_APPROVAL, APPROVED_WITHIN_POLICY, APPROVED_POLICY_EXCEPTION, APPROVED_BUDGET_EXCEPTION, APPROVED_BY_OVERRIDE, MISSING_COST_CENTER, EXPENSE_OUTSIDE_EMPLOYMENT, MISSING_RECEIPT, DUPLICATE_RECEIPT_HASH, POLICY_LIMIT_BREACH, BUDGET_EXCEEDED, REJECTED_BY_APPROVER |  |  |  |
| `final_decision_date` | date | no |  |  |  | Empty while pending |

## expense_lines

Line items of a claim with receipt metadata.

Primary key: `expense_line_id`

Foreign keys: `expense_claim_id` -> `expense_claims.expense_claim_id`, `expense_policy_id` -> `expense_policies.expense_policy_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `expense_line_id` | str:40 | yes | pattern `^EXPL-EXP-\d{4}-\d{6}-\d{2}$` |  | yes |  |
| `expense_claim_id` | str:20 | yes |  |  |  |  |
| `line_no` | int | yes |  |  |  | 1..10, no gaps inside a claim |
| `expense_policy_id` | str:10 | yes |  |  |  | Policy of the category of this line |
| `expense_date` | date | yes |  |  |  | Within the employee's employment dates |
| `merchant` | str:60 | yes |  |  |  |  |
| `amount` | dec:12,2 | yes |  | USD |  | > 0 |
| `receipt_provided` | bool | yes |  |  |  |  |
| `receipt_file_name` | str:40 | no |  |  |  | Empty when no receipt |
| `receipt_hash` | str:16 | no |  |  |  | Fingerprint of the receipt file. Same hash twice = duplicate receipt |

## approval_steps

BRIDGE between a request and the rules that apply to it: one row per approver step.

Primary key: `approval_step_id`

Foreign keys: `leave_request_id` -> `leave_requests.leave_request_id`, `expense_claim_id` -> `expense_claims.expense_claim_id`, `approval_rule_id` -> `approval_rules.approval_rule_id`, `approver_id` -> `employees.employee_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `approval_step_id` | str:40 | yes | pattern `^APR-(LVE\|EXP)-\d{4}-\d{6}-\d{2}$` |  | yes |  |
| `leave_request_id` | str:20 | no |  |  |  | Exactly one of leave_request_id / expense_claim_id is set |
| `expense_claim_id` | str:20 | no |  |  |  |  |
| `step_no` | int | yes |  |  |  | 1, 2, 3 ... in order |
| `approval_rule_id` | str:10 | yes |  |  |  | The rule that first required this role |
| `approver_role` | str:20 | yes | MANAGER, SKIP_MANAGER, HR_HEAD, FINANCE_CONTROLLER, CFO |  |  |  |
| `approver_id` | str:10 | yes |  |  |  | Must not be the requester; job_level >= rule.min_approver_level |
| `status` | str:10 | yes | APPROVED, REJECTED, PENDING, WAITING, SKIPPED |  |  |  |
| `decided_date` | date | no |  |  |  | Set only when status is APPROVED or REJECTED |
| `routing_reason` | str:200 | yes |  |  |  | Why this step exists (rule + facts) |
| `decision_reason_code` | str:30 | no | APPROVED_WITHIN_POLICY, APPROVED_POLICY_EXCEPTION, APPROVED_BUDGET_EXCEPTION, POLICY_LIMIT_BREACH, BUDGET_EXCEEDED, REJECTED_BY_APPROVER, EARLIER_STEP_REJECTED, SAME_APPROVER_EARLIER_STEP |  |  |  |
| `decision_reason` | str:200 | no |  |  |  | Human readable reason of the decision |

## reimbursements

Payment records. Created only after a claim has been fully approved.

Primary key: `reimbursement_id`

Foreign keys: `expense_claim_id` -> `expense_claims.expense_claim_id`, `employee_id` -> `employees.employee_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `reimbursement_id` | str:20 | yes | pattern `^RMB-\d{4}-\d{6}$` |  | yes |  |
| `expense_claim_id` | str:20 | yes |  |  |  | Claim must be APPROVED or REIMBURSED. One payment per claim |
| `employee_id` | str:10 | yes |  |  |  | Same employee as the claim |
| `amount` | dec:12,2 | yes |  | USD |  | = claim total_amount |
| `currency` | str:3 | yes | USD |  |  |  |
| `payment_method` | str:15 | yes | BANK_TRANSFER, PAYROLL |  |  |  |
| `approved_date` | date | yes |  |  |  | = claim final_decision_date |
| `payment_date` | date | yes |  |  |  | >= approved_date |
| `status` | str:10 | yes | PAID, SCHEDULED |  |  | PAID if payment_date <= as-of date |

## status_events

Append-only history of every status change of a request or claim. Nothing is overwritten.

Primary key: `event_id`

Foreign keys: `leave_request_id` -> `leave_requests.leave_request_id`, `expense_claim_id` -> `expense_claims.expense_claim_id`, `actor_id` -> `employees.employee_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `event_id` | str:10 | yes | pattern `^EVT-\d{6}$` |  | yes |  |
| `leave_request_id` | str:20 | no |  |  |  | Exactly one of the two request columns is set |
| `expense_claim_id` | str:20 | no |  |  |  |  |
| `from_status` | str:20 | no | SUBMITTED, PENDING_APPROVAL, APPROVED, REJECTED, REIMBURSED |  |  | Empty for the first event |
| `to_status` | str:20 | yes | SUBMITTED, PENDING_APPROVAL, APPROVED, REJECTED, REIMBURSED |  |  |  |
| `event_date` | date | yes |  |  |  |  |
| `actor_type` | str:10 | yes | SYSTEM, EMPLOYEE |  |  |  |
| `actor_id` | str:10 | no |  |  |  | Empty when actor_type is SYSTEM |
| `reason_code` | str:30 | yes | APPROVED_BUDGET_EXCEPTION, APPROVED_BY_OVERRIDE, APPROVED_POLICY_EXCEPTION, APPROVED_WITHIN_POLICY, AWAITING_APPROVAL, BUDGET_EXCEEDED, DUPLICATE_RECEIPT_HASH, EARLIER_STEP_REJECTED, EXCEEDS_MAX_CONSECUTIVE, EXPENSE_OUTSIDE_EMPLOYMENT, INSUFFICIENT_BALANCE, MISSING_COST_CENTER, MISSING_RECEIPT, NO_WORKING_DAYS, OVERLAPPING_LEAVE, POLICY_LIMIT_BREACH, REJECTED_BY_APPROVER, SAME_APPROVER_EARLIER_STEP |  |  |  |
| `note` | str:200 | no |  |  |  |  |

## ground_truth

ANSWER KEY. Known anomalies and expected decisions. Never used as an input feature.

Primary key: `ground_truth_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `ground_truth_id` | str:10 | yes | pattern `^GT-\d{6}$` |  | yes |  |
| `entity_type` | str:20 | yes | LEAVE_REQUEST, EXPENSE_CLAIM, LEAVE_BALANCE |  |  |  |
| `entity_id` | str:40 | yes |  |  |  | ID of the labelled record (checked against the tables by the validator) |
| `issue_type` | str:30 | yes | NEGATIVE_LEAVE_BALANCE, OVERLAPPING_APPROVED_LEAVE, EXPENSE_OUTSIDE_EMPLOYMENT, SPLIT_CLAIM_EVASION, MISSING_COST_CENTER, SELF_APPROVAL, DUPLICATE_REIMBURSEMENT, MISSING_RECEIPT, DUPLICATE_RECEIPT_HASH, POLICY_LIMIT_BREACH, BUDGET_EXCEEDED, INSUFFICIENT_BALANCE, OVERLAPPING_LEAVE, EXCEEDS_MAX_CONSECUTIVE, NO_WORKING_DAYS, WEEKEND_HOLIDAY_SPAN, MULTI_LEVEL_APPROVAL, BOUNDARY_AMOUNT |  |  |  |
| `origin` | str:15 | yes | INJECTED, BASELINE_RULE |  |  | INJECTED = deliberately planted; BASELINE_RULE = label derived from the documented rules |
| `expected_decision` | str:40 | yes |  |  |  | What a correct control should have done |
| `group_id` | str:20 | no |  |  |  | Links records of one scenario (e.g. split claims) |
| `notes` | str:200 | no |  |  |  |  |

## detected_exceptions

OUTPUT of the audit detectors (detectors.py). They only read the input tables.

Primary key: `detection_id`

| Field | Type | Required | Allowed values | Unit | Unique | Validation rule |
|---|---|---|---|---|---|---|
| `detection_id` | str:10 | yes | pattern `^DET-\d{6}$` |  | yes |  |
| `entity_type` | str:20 | yes | LEAVE_REQUEST, EXPENSE_CLAIM, LEAVE_BALANCE |  |  |  |
| `entity_id` | str:40 | yes |  |  |  |  |
| `issue_type` | str:30 | yes | NEGATIVE_LEAVE_BALANCE, OVERLAPPING_APPROVED_LEAVE, EXPENSE_OUTSIDE_EMPLOYMENT, SPLIT_CLAIM_EVASION, MISSING_COST_CENTER, SELF_APPROVAL, DUPLICATE_REIMBURSEMENT, MISSING_RECEIPT, DUPLICATE_RECEIPT_HASH, POLICY_LIMIT_BREACH, BUDGET_EXCEEDED, INSUFFICIENT_BALANCE, OVERLAPPING_LEAVE, EXCEEDS_MAX_CONSECUTIVE, NO_WORKING_DAYS, WEEKEND_HOLIDAY_SPAN, MULTI_LEVEL_APPROVAL, BOUNDARY_AMOUNT |  |  |  |
| `detail` | str:200 | yes |  |  |  | Human readable explanation of why it was flagged |
