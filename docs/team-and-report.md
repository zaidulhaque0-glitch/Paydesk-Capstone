# Paydesk · Team handoff and short capstone report

## Project and use case
A mid-sized IT firm needs HR to reconcile attendance, approve leave and deliver a consistent monthly salary slip. Paydesk gives HR a monthly register and an employee self-service view. An unresolved weekday blocks a batch, so HR can fix the underlying record before money is posted.

## One employee, one pay run
The calendar has 22 workdays in September 2026. Ananya Rao has 20 present days, one approved paid leave day and one absence. Her September salary revision raises the monthly rate from ₹72,000 to ₹75,000.

| Step | Calculation | Result |
|---|---|---|
| Paid days | 20 present + 1 approved leave | 21 |
| Gross | Round half up (75,000 × 21 / 22) | ₹71,591 |
| Classroom tax | Round half up (31,591 × 10%) | ₹3,159 |
| Net | 71,591 − 3,159 | **₹68,432** |

The first ₹40,000 of earned gross is exempt. The next ₹40,000 is taxed at 10% and the excess at 20%. This is a fictional monthly policy for the exercise. Late arrival is reported separately and carries no extra deduction. Approved leave counts once per eligible weekday. A mid-month joiner earns only eligible paid days against the full-month denominator.

## How a click becomes a committed batch
The HR form sends an authenticated POST with a session-bound CSRF token. Flask resolves the current account, checks its HR role and starts one database transaction. A write lock serializes app writers. The service creates a pay period, checks every eligible employee, finds the latest applicable salary and inserts each payslip. A missing rate, unmarked day or constraint failure rolls back the entire transaction, including previously inserted slips. A second request for the same month finds a posted period. Triggers protect the underlying attendance, approved leave and salary history after posting.

Employees have read-only application access. The server reads the employee code from the authenticated account and applies it to queries, CSV exports and slip routes. The employee portal has no payroll mutation endpoint it can use. An HR user can manage employee records, effective-dated salary, daily time and leave approvals. Individual employees never receive database credentials.

## Reports and optimization
Monthly attendance starts with the work calendar for each eligible employee, then joins marks and checks approved leave. It counts absent, leave and unmarked days independently. The late-marks report selects present records with a clock-in later than 550 minutes after midnight. A salary-slip query joins payroll, pay period, employee and salary and invokes the two tax and pay functions. Name and department labels reflect current employee profiles.

The standard attendance primary key starts with employee code. A firm-wide monthly late report filters first by date and needs only late arrivals. A partial index on (work_date, employee_code) for those rows changes the SQLite plan from a scan to an index range search. The included trace records the plan and virtual-machine instructions on identical data. Instruction counts describe this fixture and engine.

## Suggested team split
| Owner | Work to understand and present | Handoff |
|---|---|---|
| Schema lead | ER relationships, constraints, salary history, 3NF | Get Phase 1 approved, then share the frozen DDL and key names. |
| Backend lead | Stored functions, payroll transactions, leave/attendance triggers | Walk through the Ananya calculation and forced rollback. |
| Reports and QA lead | Three SQL reports, CSV, indexes, access and boundary tests | Reproduce test results and explain the measured plan change. |
| UI and integration lead | HR workflow, employee views, printable slip, README and rehearsal | Run the demo from a clean extraction and verify both logins. |

For three members, combine reports/QA with UI integration. For five, assign access control and testing to a separate person. Use the approved schema for every handoff. Each person should be able to explain how their screen or report reaches a database constraint.

## Five-minute presentation
| Time | Presenter action |
|---|---|
| 0:00–0:45 | Show the ER diagram. Explain why Salary needs an effective month and why Payroll references a particular revision. |
| 0:45–1:45 | Show HR's September dashboard and Ananya's attendance counts. Open the late report and show its index trace. |
| 1:45–2:45 | Post September and open Ananya's payslip. Reconcile the four numbers in the worked example. |
| 2:45–3:45 | Sign in as Ananya and show only her records. Open the URL for a different employee's slip and show HTTP 403. |
| 3:45–5:00 | Show the failed-batch test and its rollback assertions. Describe how two simultaneous post requests leave one complete batch. |

## Scaling to a larger firm
A larger deployment could keep the relational model and use a managed PostgreSQL server, pooled connections and a production web server behind HTTPS. Introduce per-employee locks for edits and period-level locking for pay runs if measured write contention grows. Date partitioning and report caches are candidates after measuring actual volumes. Version tax schedules before changing historic tax rules. Add effective-dated employment end dates, regional holiday calendars, immutable payslip documents and an approval audit trail as business requirements expand.

## Scope of the demo
The calendar covers weekdays from 2025 through 2035. It assumes a single day shift and a 09:10 grace cutoff. HR enters and decides leave requests. The seed contains fictional employees across Engineering, Design, IT Operations and People. Full months can be posted after they end. The fixed policy and shared demo logins suit a class presentation. Live payroll would require organization-specific policies, verified statutory calculations and individual production credentials.

