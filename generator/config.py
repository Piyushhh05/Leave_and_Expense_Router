"""
config.py - every constant used by the generator lives here.

If an interviewer asks "where does the number 500 come from?", the answer is
always "config.py / rules.py" - nothing is hidden inside the logic.
"""
from datetime import date

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
SEED = 20261022                 # same seed -> same data, every time
AS_OF_DATE = date(2026, 10, 22) # the dataset's "today". We never call date.today()
YEAR = 2026                     # balance year and the year inside IDs

# Default volumes from the problem statement. --scale multiplies all three.
DEFAULT_COUNTS = {"employees": 400, "leave_requests": 800, "expense_claims": 1000}

# ---------------------------------------------------------------------------
# Organisation
# ---------------------------------------------------------------------------
COUNTRIES = ["IN", "US", "UK", "DE"]
COUNTRY_WEIGHTS = [45, 25, 15, 15]

# The six departments each get one VP. The CEO sits in "Executive".
DEPARTMENTS = ["Engineering", "Sales", "Finance", "HR", "Operations", "Marketing"]

# job_level -> title. Only levels 1-3 raise requests (see README "Simplifications").
JOB_TITLES = {1: "Associate", 2: "Manager", 3: "Director", 4: "Vice President", 5: "CEO"}

# Share of the headcount that is a Director / Manager. Everyone else is staff.
DIRECTOR_SHARE = 0.05
MANAGER_SHARE = 0.15
TERMINATED_SHARE_OF_STAFF = 0.05
NEW_HIRE_2026_SHARE_OF_STAFF = 0.12

# ---------------------------------------------------------------------------
# Leave policies (6 of them, as required)
# annual_days = yearly entitlement, accrual_per_month = credited each month
# ---------------------------------------------------------------------------
LEAVE_POLICIES = [
    # id,       name,                       type,     countries, annual, per_month, carry cap, max consecutive, deducts balance
    ("LPOL-01", "Annual Leave - India",     "ANNUAL", "IN",      18,     1.50,      5,         15,             True),
    ("LPOL-02", "Annual Leave - USA",       "ANNUAL", "US",      15,     1.25,      5,         15,             True),
    ("LPOL-03", "Annual Leave - UK/Germany", "ANNUAL", "UK|DE",  24,     2.00,      5,         20,             True),
    ("LPOL-04", "Sick Leave - Global",      "SICK",   "ALL",     12,     1.00,      0,         5,              True),
    ("LPOL-05", "Casual Leave - Global",    "CASUAL", "ALL",     6,      0.50,      0,         2,              True),
    ("LPOL-06", "Unpaid Leave - Global",    "UNPAID", "ALL",     0,      0.00,      0,         30,             False),
]
ANNUAL_POLICY_BY_COUNTRY = {"IN": "LPOL-01", "US": "LPOL-02", "UK": "LPOL-03", "DE": "LPOL-03"}
POLICY_BY_TYPE = {"SICK": "LPOL-04", "CASUAL": "LPOL-05", "UNPAID": "LPOL-06"}

# Mix of leave types in the generated requests
LEAVE_TYPES = ["ANNUAL", "SICK", "CASUAL", "UNPAID"]
LEAVE_TYPE_WEIGHTS = [55, 20, 15, 10]

# Length of a request in CALENDAR days. Business days are computed from this.
LEAVE_LENGTH_CHOICES = {
    "ANNUAL": ([1, 2, 3, 4, 5, 7, 9, 12, 14, 16], [14, 16, 16, 14, 14, 10, 6, 5, 3, 2]),
    "SICK":   ([1, 2, 3, 4, 5, 7],                [35, 30, 20, 8, 5, 2]),
    "CASUAL": ([1, 2, 3],                         [60, 35, 5]),
    "UNPAID": ([2, 5, 10, 14, 20],                [25, 30, 20, 15, 10]),
}

# Leave requests start from this date: accrual needs a few months to build up
LEAVE_EARLIEST_START = date(2026, 2, 16)

# Leave approval thresholds (business days). See rules.APPROVAL_RULES.
LEAVE_SKIP_LEVEL_ABOVE_DAYS = 3
LEAVE_HR_ABOVE_DAYS = 10

# ---------------------------------------------------------------------------
# Expense policies: one per category
# ---------------------------------------------------------------------------
EXPENSE_POLICIES = [
    # id,       category,              max per line (USD), receipt required above (USD)
    ("EPOL-01", "MEALS",                100,                25),
    ("EPOL-02", "TRAVEL",               1500,               0),
    ("EPOL-03", "LODGING",              450,                0),
    ("EPOL-04", "SUPPLIES",             300,                20),
    ("EPOL-05", "TRAINING",             3000,               0),
    ("EPOL-06", "CLIENT_ENTERTAINMENT", 600,                0),
    ("EPOL-07", "SOFTWARE",             400,                0),
    ("EPOL-08", "EQUIPMENT",            3500,               0),
]
# category -> (lowest amount, most likely amount). The highest normal amount is the
# policy limit itself, so a normal line never breaches its limit.
AMOUNT_RANGES = {
    "MEALS": (8, 30),
    "TRAVEL": (40, 350),
    "LODGING": (80, 220),
    "SUPPLIES": (10, 60),
    "TRAINING": (100, 900),
    "CLIENT_ENTERTAINMENT": (60, 220),
    "SOFTWARE": (10, 90),
    "EQUIPMENT": (300, 1200),
}
# Breaches are created on purpose: this share of lines is made 2%-40% above the limit.
P_POLICY_BREACH_LINE = 0.04
BREACH_FACTOR_RANGE = (1.02, 1.40)
CATEGORY_WEIGHTS = {
    "MEALS": 28, "TRAVEL": 20, "LODGING": 12, "SUPPLIES": 14,
    "TRAINING": 6, "CLIENT_ENTERTAINMENT": 8, "SOFTWARE": 8, "EQUIPMENT": 4,
}
# Lines per claim 1..10. Most claims are small, a few are big.
LINES_PER_CLAIM_WEIGHTS = [30, 25, 15, 10, 6, 5, 3, 3, 2, 1]
BULK_CLAIM_SHARE = 0.03          # 3% of claims are "project purchases" with 4-10 big lines
BULK_CATEGORIES = ["EQUIPMENT", "TRAINING"]

# Expense approval thresholds (USD, total of the claim)
EXPENSE_SKIP_LEVEL_ABOVE = 500
EXPENSE_FINANCE_ABOVE = 2000
EXPENSE_CFO_ABOVE = 10000
EXPENSE_REGIONAL_REVIEW_ABOVE = 1000       # extra Finance review for DE / UK claims
REGIONAL_REVIEW_COUNTRIES = "DE|UK"

# Exception-path tolerances
POLICY_EXCEPTION_TOLERANCE = 1.20  # a line up to 120% of the limit can be approved by Finance as an exception
BUDGET_OVERSHOOT_LIMIT = 0.10      # CFO rejects if the cost centre would overshoot its budget by more than 10%
BUDGET_PER_HEAD = 3600                # annual budget of a cost centre = headcount x this (USD), tuned so ~5% of claims exceed it

# ---------------------------------------------------------------------------
# Probabilities for the BASELINE data (these create natural exceptions)
# ---------------------------------------------------------------------------
P_MISSING_RECEIPT = 0.015    # per line where a receipt is required
P_OPTIONAL_RECEIPT = 0.70    # per line where a receipt is NOT required
P_DUPLICATE_RECEIPT = 0.025  # per claim: reuse an earlier receipt of the same employee
P_OVERLAP_LEAVE = 0.04       # per leave request: overlaps an earlier request of the same person
P_HOLIDAY_LEAVE = 0.08       # per leave request: built around a public holiday
P_WEEKDAY_START = 0.90       # leave usually starts on a weekday

# ---------------------------------------------------------------------------
# Timing (turnaround days for each approval step; affects dates, not outcomes)
# ---------------------------------------------------------------------------
STEP_TURNAROUND_DAYS = (1, 3)
PAYMENT_DELAY_DAYS = (3, 7)

# ---------------------------------------------------------------------------
# Injected edge cases (counts at scale 1.0). Each gets a ground-truth label.
# ---------------------------------------------------------------------------
INJECTED = {
    "NEGATIVE_LEAVE_BALANCE": 8,       # approved leave that pushes the balance below zero
    "OVERLAPPING_APPROVED_LEAVE": 5,   # pairs of approved requests that overlap
    "EXPENSE_OUTSIDE_EMPLOYMENT": 8,   # expense dated before hire / after termination
    "SPLIT_CLAIM_EVASION": 6,          # groups of 3 claims just under the 500 threshold
    "MISSING_COST_CENTER": 8,          # approved claim with no cost centre
    "SELF_APPROVAL": 6,                # requester approves their own request
    "DUPLICATE_REIMBURSEMENT": 5,      # claim paid twice
}
SPLIT_GROUP_SIZE = 3

# ---------------------------------------------------------------------------
# Illustrative public holidays for 2026. NOT an official calendar - they only
# exist so business-day counting has something to exclude.
# ---------------------------------------------------------------------------
HOLIDAYS = [
    ("IN", date(2026, 1, 26), "Republic Day"),
    ("IN", date(2026, 8, 15), "Independence Day"),
    ("IN", date(2026, 10, 2), "Gandhi Jayanti"),
    ("IN", date(2026, 11, 9), "Festival of Lights (illustrative)"),
    ("IN", date(2026, 12, 25), "Christmas Day"),
    ("US", date(2026, 1, 1), "New Year's Day"),
    ("US", date(2026, 5, 25), "Memorial Day"),
    ("US", date(2026, 7, 3), "Independence Day (observed)"),
    ("US", date(2026, 9, 7), "Labor Day"),
    ("US", date(2026, 11, 26), "Thanksgiving"),
    ("US", date(2026, 12, 25), "Christmas Day"),
    ("UK", date(2026, 1, 1), "New Year's Day"),
    ("UK", date(2026, 4, 3), "Good Friday"),
    ("UK", date(2026, 4, 6), "Easter Monday"),
    ("UK", date(2026, 5, 4), "Early May Bank Holiday"),
    ("UK", date(2026, 8, 31), "Summer Bank Holiday"),
    ("UK", date(2026, 12, 25), "Christmas Day"),
    ("UK", date(2026, 12, 28), "Boxing Day (substitute)"),
    ("DE", date(2026, 1, 1), "New Year's Day"),
    ("DE", date(2026, 4, 3), "Good Friday"),
    ("DE", date(2026, 4, 6), "Easter Monday"),
    ("DE", date(2026, 5, 1), "Labour Day"),
    ("DE", date(2026, 10, 3), "German Unity Day"),
    ("DE", date(2026, 12, 25), "Christmas Day"),
    ("DE", date(2026, 12, 26), "Second Day of Christmas"),
]

# ---------------------------------------------------------------------------
# Synthetic names (made up for this project, no real people / no external data)
# ---------------------------------------------------------------------------
FIRST_NAMES = [
    "Aarav", "Diya", "Rohan", "Meera", "Kabir", "Anaya", "Vikram", "Isha", "Arjun", "Nisha",
    "Liam", "Olivia", "Noah", "Emma", "Ethan", "Ava", "Mason", "Mia", "Lucas", "Zoe",
    "Oliver", "Amelia", "George", "Freya", "Harry", "Isla", "Jack", "Poppy", "Leo", "Grace",
    "Lukas", "Anna", "Felix", "Marie", "Jonas", "Lena", "Paul", "Sophie", "Max", "Clara",
]
LAST_NAMES = [
    "Sharma", "Patel", "Nayak", "Mishra", "Das", "Reddy", "Iyer", "Menon", "Singh", "Kapoor",
    "Smith", "Johnson", "Brown", "Miller", "Davis", "Wilson", "Moore", "Taylor", "Clark", "Hall",
    "Evans", "Walker", "Wright", "Hughes", "Turner", "Baker", "Carter", "Reid", "Ward", "Cole",
    "Meyer", "Schmidt", "Fischer", "Weber", "Wagner", "Becker", "Hoffmann", "Koch", "Richter", "Klein",
]
MERCHANT_PREFIX = {
    "MEALS": "Cafe", "TRAVEL": "Transit Co", "LODGING": "Hotel", "SUPPLIES": "Office Mart",
    "TRAINING": "Learning Hub", "CLIENT_ENTERTAINMENT": "Dining Group", "SOFTWARE": "SoftTools",
    "EQUIPMENT": "Tech Store",
}
LEAVE_REASONS = {
    "ANNUAL": ["Family trip", "Personal time off", "Festival break", "Travel plans", "Rest and recharge"],
    "SICK": ["Fever", "Medical appointment", "Not feeling well", "Recovering at home"],
    "CASUAL": ["Personal errand", "Home maintenance", "Family function"],
    "UNPAID": ["Extended personal break", "Further study", "Family commitment"],
}
CLAIM_PURPOSES = [
    "Client visit", "Team offsite", "Conference attendance", "Monthly office expenses",
    "Project purchase", "Training course", "Business trip", "Customer lunch",
]

# Claims whose total is EXACTLY on an approval threshold (boundary tests). Each is (total, [(category, amount), ...])
BOUNDARY_CLAIMS = [
    (500.00,   [("TRAVEL", 250.00), ("TRAVEL", 250.00)]),
    (2000.00,  [("TRAINING", 2000.00)]),
    (10000.00, [("EQUIPMENT", 2500.00)] * 4),
    (500.00,   [("LODGING", 150.00), ("LODGING", 150.00), ("LODGING", 200.00)]),
    (2000.00,  [("TRAVEL", 1000.00), ("TRAVEL", 1000.00)]),
    (10000.00, [("TRAINING", 2500.00)] * 4),
]
