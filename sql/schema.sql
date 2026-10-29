-- MySQL schema generated from generator/schema_spec.py
-- Re-create with: python -m generator.schema_spec

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS detected_exceptions;
DROP TABLE IF EXISTS ground_truth;
DROP TABLE IF EXISTS status_events;
DROP TABLE IF EXISTS reimbursements;
DROP TABLE IF EXISTS approval_steps;
DROP TABLE IF EXISTS expense_lines;
DROP TABLE IF EXISTS expense_claims;
DROP TABLE IF EXISTS leave_requests;
DROP TABLE IF EXISTS approval_rules;
DROP TABLE IF EXISTS expense_policies;
DROP TABLE IF EXISTS leave_balances;
DROP TABLE IF EXISTS leave_policies;
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS cost_centers;
DROP TABLE IF EXISTS holidays;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE holidays (
  holiday_id VARCHAR(8) NOT NULL,
  holiday_date DATE NOT NULL,
  country ENUM('IN', 'US', 'UK', 'DE') NOT NULL,
  name VARCHAR(60) NOT NULL,
  PRIMARY KEY (holiday_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE cost_centers (
  cost_center_id VARCHAR(10) NOT NULL,
  name VARCHAR(60) NOT NULL,
  country ENUM('IN', 'US', 'UK', 'DE') NOT NULL,
  department ENUM('Engineering', 'Sales', 'Finance', 'HR', 'Operations', 'Marketing', 'Executive') NOT NULL,
  annual_budget DECIMAL(12,2) NOT NULL,
  PRIMARY KEY (cost_center_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE employees (
  employee_id VARCHAR(10) NOT NULL,
  full_name VARCHAR(60) NOT NULL,
  email VARCHAR(80) NOT NULL,
  country ENUM('IN', 'US', 'UK', 'DE') NOT NULL,
  department ENUM('Engineering', 'Sales', 'Finance', 'HR', 'Operations', 'Marketing', 'Executive') NOT NULL,
  job_level INT NOT NULL,
  job_title VARCHAR(30) NOT NULL,
  manager_id VARCHAR(10) NULL,
  cost_center_id VARCHAR(10) NOT NULL,
  hire_date DATE NOT NULL,
  termination_date DATE NULL,
  status ENUM('ACTIVE', 'TERMINATED') NOT NULL,
  special_role ENUM('FINANCE_CONTROLLER', 'CFO', 'HR_HEAD') NULL,
  PRIMARY KEY (employee_id),
  UNIQUE KEY uq_employees_email (email),
  CONSTRAINT fk_employees_manager_id FOREIGN KEY (manager_id) REFERENCES employees (employee_id),
  CONSTRAINT fk_employees_cost_center_id FOREIGN KEY (cost_center_id) REFERENCES cost_centers (cost_center_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE leave_policies (
  leave_policy_id VARCHAR(10) NOT NULL,
  name VARCHAR(60) NOT NULL,
  leave_type ENUM('ANNUAL', 'SICK', 'CASUAL', 'UNPAID') NOT NULL,
  applies_to_countries VARCHAR(10) NOT NULL,
  annual_days DECIMAL(6,2) NOT NULL,
  accrual_per_month DECIMAL(6,2) NOT NULL,
  carry_forward_cap DECIMAL(6,2) NOT NULL,
  max_consecutive_days INT NOT NULL,
  deducts_balance TINYINT(1) NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  PRIMARY KEY (leave_policy_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE leave_balances (
  leave_balance_id VARCHAR(20) NOT NULL,
  employee_id VARCHAR(10) NOT NULL,
  leave_policy_id VARCHAR(10) NOT NULL,
  balance_year INT NOT NULL,
  opening_balance DECIMAL(6,2) NOT NULL,
  accrued_days DECIMAL(6,2) NOT NULL,
  used_days DECIMAL(6,2) NOT NULL,
  pending_days DECIMAL(6,2) NOT NULL,
  available_days DECIMAL(6,2) NOT NULL,
  as_of_date DATE NOT NULL,
  PRIMARY KEY (leave_balance_id),
  UNIQUE KEY uq_leave_balances_combo (employee_id, leave_policy_id, balance_year),
  CONSTRAINT fk_leave_balances_employee_id FOREIGN KEY (employee_id) REFERENCES employees (employee_id),
  CONSTRAINT fk_leave_balances_leave_policy_id FOREIGN KEY (leave_policy_id) REFERENCES leave_policies (leave_policy_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE expense_policies (
  expense_policy_id VARCHAR(10) NOT NULL,
  category ENUM('MEALS', 'TRAVEL', 'LODGING', 'SUPPLIES', 'TRAINING', 'CLIENT_ENTERTAINMENT', 'SOFTWARE', 'EQUIPMENT') NOT NULL,
  max_line_amount DECIMAL(12,2) NOT NULL,
  receipt_required_above DECIMAL(12,2) NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  PRIMARY KEY (expense_policy_id),
  UNIQUE KEY uq_expense_policies_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE approval_rules (
  approval_rule_id VARCHAR(10) NOT NULL,
  domain ENUM('LEAVE', 'EXPENSE') NOT NULL,
  step_role ENUM('MANAGER', 'SKIP_MANAGER', 'HR_HEAD', 'FINANCE_CONTROLLER', 'CFO') NOT NULL,
  condition_type ENUM('ALWAYS', 'DAYS_ABOVE', 'LEAVE_TYPE', 'AMOUNT_ABOVE', 'CATEGORY', 'COUNTRY_AMOUNT', 'POLICY_BREACH', 'BUDGET_EXCEEDED') NOT NULL,
  threshold DECIMAL(12,2) NULL,
  match_value VARCHAR(30) NULL,
  min_approver_level INT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  description VARCHAR(120) NOT NULL,
  PRIMARY KEY (approval_rule_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE leave_requests (
  leave_request_id VARCHAR(20) NOT NULL,
  employee_id VARCHAR(10) NOT NULL,
  leave_policy_id VARCHAR(10) NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  calendar_days INT NOT NULL,
  business_days INT NOT NULL,
  submitted_date DATE NOT NULL,
  request_reason VARCHAR(80) NOT NULL,
  balance_at_submission DECIMAL(6,2) NULL,
  status ENUM('SUBMITTED', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED') NOT NULL,
  final_reason_code ENUM('AWAITING_APPROVAL', 'APPROVED_WITHIN_POLICY', 'APPROVED_BY_OVERRIDE', 'NO_WORKING_DAYS', 'OVERLAPPING_LEAVE', 'INSUFFICIENT_BALANCE', 'EXCEEDS_MAX_CONSECUTIVE', 'REJECTED_BY_APPROVER') NOT NULL,
  final_decision_date DATE NULL,
  PRIMARY KEY (leave_request_id),
  CONSTRAINT fk_leave_requests_employee_id FOREIGN KEY (employee_id) REFERENCES employees (employee_id),
  CONSTRAINT fk_leave_requests_leave_policy_id FOREIGN KEY (leave_policy_id) REFERENCES leave_policies (leave_policy_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE expense_claims (
  expense_claim_id VARCHAR(20) NOT NULL,
  employee_id VARCHAR(10) NOT NULL,
  cost_center_id VARCHAR(10) NULL,
  employee_country ENUM('IN', 'US', 'UK', 'DE') NOT NULL,
  submitted_date DATE NOT NULL,
  purpose VARCHAR(80) NOT NULL,
  currency ENUM('USD') NOT NULL,
  total_amount DECIMAL(12,2) NOT NULL,
  line_count INT NOT NULL,
  has_policy_breach TINYINT(1) NOT NULL,
  budget_exceeded TINYINT(1) NOT NULL,
  status ENUM('SUBMITTED', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'REIMBURSED') NOT NULL,
  final_reason_code ENUM('AWAITING_APPROVAL', 'APPROVED_WITHIN_POLICY', 'APPROVED_POLICY_EXCEPTION', 'APPROVED_BUDGET_EXCEPTION', 'APPROVED_BY_OVERRIDE', 'MISSING_COST_CENTER', 'EXPENSE_OUTSIDE_EMPLOYMENT', 'MISSING_RECEIPT', 'DUPLICATE_RECEIPT_HASH', 'POLICY_LIMIT_BREACH', 'BUDGET_EXCEEDED', 'REJECTED_BY_APPROVER') NOT NULL,
  final_decision_date DATE NULL,
  PRIMARY KEY (expense_claim_id),
  CONSTRAINT fk_expense_claims_employee_id FOREIGN KEY (employee_id) REFERENCES employees (employee_id),
  CONSTRAINT fk_expense_claims_cost_center_id FOREIGN KEY (cost_center_id) REFERENCES cost_centers (cost_center_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE expense_lines (
  expense_line_id VARCHAR(40) NOT NULL,
  expense_claim_id VARCHAR(20) NOT NULL,
  line_no INT NOT NULL,
  expense_policy_id VARCHAR(10) NOT NULL,
  expense_date DATE NOT NULL,
  merchant VARCHAR(60) NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  receipt_provided TINYINT(1) NOT NULL,
  receipt_file_name VARCHAR(40) NULL,
  receipt_hash VARCHAR(16) NULL,
  PRIMARY KEY (expense_line_id),
  UNIQUE KEY uq_expense_lines_combo (expense_claim_id, line_no),
  CONSTRAINT fk_expense_lines_expense_claim_id FOREIGN KEY (expense_claim_id) REFERENCES expense_claims (expense_claim_id),
  CONSTRAINT fk_expense_lines_expense_policy_id FOREIGN KEY (expense_policy_id) REFERENCES expense_policies (expense_policy_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE approval_steps (
  approval_step_id VARCHAR(40) NOT NULL,
  leave_request_id VARCHAR(20) NULL,
  expense_claim_id VARCHAR(20) NULL,
  step_no INT NOT NULL,
  approval_rule_id VARCHAR(10) NOT NULL,
  approver_role ENUM('MANAGER', 'SKIP_MANAGER', 'HR_HEAD', 'FINANCE_CONTROLLER', 'CFO') NOT NULL,
  approver_id VARCHAR(10) NOT NULL,
  status ENUM('APPROVED', 'REJECTED', 'PENDING', 'WAITING', 'SKIPPED') NOT NULL,
  decided_date DATE NULL,
  routing_reason VARCHAR(200) NOT NULL,
  decision_reason_code ENUM('APPROVED_WITHIN_POLICY', 'APPROVED_POLICY_EXCEPTION', 'APPROVED_BUDGET_EXCEPTION', 'POLICY_LIMIT_BREACH', 'BUDGET_EXCEEDED', 'REJECTED_BY_APPROVER', 'EARLIER_STEP_REJECTED', 'SAME_APPROVER_EARLIER_STEP') NULL,
  decision_reason VARCHAR(200) NULL,
  PRIMARY KEY (approval_step_id),
  CONSTRAINT fk_approval_steps_leave_request_id FOREIGN KEY (leave_request_id) REFERENCES leave_requests (leave_request_id),
  CONSTRAINT fk_approval_steps_expense_claim_id FOREIGN KEY (expense_claim_id) REFERENCES expense_claims (expense_claim_id),
  CONSTRAINT fk_approval_steps_approval_rule_id FOREIGN KEY (approval_rule_id) REFERENCES approval_rules (approval_rule_id),
  CONSTRAINT fk_approval_steps_approver_id FOREIGN KEY (approver_id) REFERENCES employees (employee_id),
  CONSTRAINT ck_approval_steps_1 CHECK ((leave_request_id IS NULL) <> (expense_claim_id IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE reimbursements (
  reimbursement_id VARCHAR(20) NOT NULL,
  expense_claim_id VARCHAR(20) NOT NULL,
  employee_id VARCHAR(10) NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  currency ENUM('USD') NOT NULL,
  payment_method ENUM('BANK_TRANSFER', 'PAYROLL') NOT NULL,
  approved_date DATE NOT NULL,
  payment_date DATE NOT NULL,
  status ENUM('PAID', 'SCHEDULED') NOT NULL,
  PRIMARY KEY (reimbursement_id),
  CONSTRAINT fk_reimbursements_expense_claim_id FOREIGN KEY (expense_claim_id) REFERENCES expense_claims (expense_claim_id),
  CONSTRAINT fk_reimbursements_employee_id FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE status_events (
  event_id VARCHAR(10) NOT NULL,
  leave_request_id VARCHAR(20) NULL,
  expense_claim_id VARCHAR(20) NULL,
  from_status ENUM('SUBMITTED', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'REIMBURSED') NULL,
  to_status ENUM('SUBMITTED', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'REIMBURSED') NOT NULL,
  event_date DATE NOT NULL,
  actor_type ENUM('SYSTEM', 'EMPLOYEE') NOT NULL,
  actor_id VARCHAR(10) NULL,
  reason_code ENUM('APPROVED_BUDGET_EXCEPTION', 'APPROVED_BY_OVERRIDE', 'APPROVED_POLICY_EXCEPTION', 'APPROVED_WITHIN_POLICY', 'AWAITING_APPROVAL', 'BUDGET_EXCEEDED', 'DUPLICATE_RECEIPT_HASH', 'EARLIER_STEP_REJECTED', 'EXCEEDS_MAX_CONSECUTIVE', 'EXPENSE_OUTSIDE_EMPLOYMENT', 'INSUFFICIENT_BALANCE', 'MISSING_COST_CENTER', 'MISSING_RECEIPT', 'NO_WORKING_DAYS', 'OVERLAPPING_LEAVE', 'POLICY_LIMIT_BREACH', 'REJECTED_BY_APPROVER', 'SAME_APPROVER_EARLIER_STEP') NOT NULL,
  note VARCHAR(200) NULL,
  PRIMARY KEY (event_id),
  CONSTRAINT fk_status_events_leave_request_id FOREIGN KEY (leave_request_id) REFERENCES leave_requests (leave_request_id),
  CONSTRAINT fk_status_events_expense_claim_id FOREIGN KEY (expense_claim_id) REFERENCES expense_claims (expense_claim_id),
  CONSTRAINT fk_status_events_actor_id FOREIGN KEY (actor_id) REFERENCES employees (employee_id),
  CONSTRAINT ck_status_events_1 CHECK ((leave_request_id IS NULL) <> (expense_claim_id IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE ground_truth (
  ground_truth_id VARCHAR(10) NOT NULL,
  entity_type ENUM('LEAVE_REQUEST', 'EXPENSE_CLAIM', 'LEAVE_BALANCE') NOT NULL,
  entity_id VARCHAR(40) NOT NULL,
  issue_type ENUM('NEGATIVE_LEAVE_BALANCE', 'OVERLAPPING_APPROVED_LEAVE', 'EXPENSE_OUTSIDE_EMPLOYMENT', 'SPLIT_CLAIM_EVASION', 'MISSING_COST_CENTER', 'SELF_APPROVAL', 'DUPLICATE_REIMBURSEMENT', 'MISSING_RECEIPT', 'DUPLICATE_RECEIPT_HASH', 'POLICY_LIMIT_BREACH', 'BUDGET_EXCEEDED', 'INSUFFICIENT_BALANCE', 'OVERLAPPING_LEAVE', 'EXCEEDS_MAX_CONSECUTIVE', 'NO_WORKING_DAYS', 'WEEKEND_HOLIDAY_SPAN', 'MULTI_LEVEL_APPROVAL', 'BOUNDARY_AMOUNT') NOT NULL,
  origin ENUM('INJECTED', 'BASELINE_RULE') NOT NULL,
  expected_decision VARCHAR(40) NOT NULL,
  group_id VARCHAR(20) NULL,
  notes VARCHAR(200) NULL,
  PRIMARY KEY (ground_truth_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE detected_exceptions (
  detection_id VARCHAR(10) NOT NULL,
  entity_type ENUM('LEAVE_REQUEST', 'EXPENSE_CLAIM', 'LEAVE_BALANCE') NOT NULL,
  entity_id VARCHAR(40) NOT NULL,
  issue_type ENUM('NEGATIVE_LEAVE_BALANCE', 'OVERLAPPING_APPROVED_LEAVE', 'EXPENSE_OUTSIDE_EMPLOYMENT', 'SPLIT_CLAIM_EVASION', 'MISSING_COST_CENTER', 'SELF_APPROVAL', 'DUPLICATE_REIMBURSEMENT', 'MISSING_RECEIPT', 'DUPLICATE_RECEIPT_HASH', 'POLICY_LIMIT_BREACH', 'BUDGET_EXCEEDED', 'INSUFFICIENT_BALANCE', 'OVERLAPPING_LEAVE', 'EXCEEDS_MAX_CONSECUTIVE', 'NO_WORKING_DAYS', 'WEEKEND_HOLIDAY_SPAN', 'MULTI_LEVEL_APPROVAL', 'BOUNDARY_AMOUNT') NOT NULL,
  detail VARCHAR(200) NOT NULL,
  PRIMARY KEY (detection_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
