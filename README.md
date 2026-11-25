# Paydesk
A payroll and attendance capstone for a mid-sized IT firm. HR records time, approves leave and posts monthly payroll. Employees sign in to inspect their own attendance, leave and printable salary slips.

## Run the demo
Use Python 3.10 or newer. Extract the ZIP. On Windows, double-click `Start-Paydesk.cmd` for the local demo, then open the address below. For manual setup, open a terminal in the folder containing `app.py`.

**Windows**
```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

**macOS or Linux**
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Open **http://127.0.0.1:5050**. The first launch creates a local database and seeds it. Later launches reuse it. The app runs offline after its dependencies are installed. Stop the server with Ctrl+C.

| Sign in as | Email | Demo password |
|---|---|---|
| HR / Admin | `hr@paydesk.test` | `CampusDemo26!` |
| Employee | `ananya@paydesk.test` | `CampusDemo26!` |

All people and pay records are fictional. Demo accounts appear on the sign-in page for the classroom presentation. The server binds to loopback.

## Which database to use
Both backends install **the same nine tables**, financial expressions, constraints and report queries. Choose your team's demonstration engine before Phase 1 review.

- **PostgreSQL** is the rubric path for native stored functions. It installs `gross_pay` and `tax_due` in the PostgreSQL database, plus PL/pgSQL validation triggers. Follow the setup below.
- **SQLite** is the quick local demo and the engine used for the included test evidence. Its adapter registers the same SQL function bodies on every connection. SQLite has no native `CREATE FUNCTION` statement. The application installs native SQLite triggers.

## PostgreSQL setup
Use a dedicated empty PostgreSQL 16 database owned by an account that can create tables, indexes and functions. With Docker installed, the included Compose file can supply it locally.

```powershell
docker compose up -d --wait
.\.venv\Scripts\python -m pip install -r requirements-postgres.txt
$env:PAYDESK_DATABASE_URL = "postgresql://paydesk:classroom_local@127.0.0.1:55432/paydesk"
.\.venv\Scripts\python app.py
```

On macOS/Linux set the variable with `export PAYDESK_DATABASE_URL='postgresql://paydesk:classroom_local@127.0.0.1:55432/paydesk'` and use `.venv/bin/python`. For an existing PostgreSQL installation, use the connection URL for your own empty database and skip Docker. Each database initializes its own sample rows on first launch.

In psql or pgAdmin, try the installed functions after starting the app.
```sql
SELECT gross_pay(75000, 21, 22) AS gross,
       tax_due(gross_pay(75000, 21, 22)) AS tax;
```
Expected values are ₹71,591 gross and ₹3,159 demo tax. App roles are enforced by the Flask server. The database connection belongs to the server and is never issued to an employee. In your dedicated classroom database, run `sql/explain_postgres.sql` to compare the late report before and after its index and roll back the experiment.

## First demo
1. Sign in as HR. September 2026 opens with 12 people and complete time records. Compare August (already posted) with September (open).
2. Open **Reports → Late marks** for September. Download the 42 underlying records. An arrival at 09:10 is on time, and an arrival at 09:11 is late.
3. Open **Payroll → Post payroll** for September. Open Ananya's slip. She worked 20 days and had 1 paid leave day out of 22 working days. Gross pay is ₹71,591 and net pay is ₹68,432.
4. Sign out, then sign in as Ananya. Open her slip and print it or save it as a PDF. Changing the slip URL from `IT-001` to `IT-002` returns HTTP 403.
5. In an HR session, select **October 2026** to manage an open period with a pending leave request. New employee, salary revision, attendance and leave forms are available in the sidebar sections.

Posting locks the period. For a second rehearsal, point `PAYDESK_DATABASE_URL` at a **new local SQLite filename** before starting the app. For example use `$env:PAYDESK_DATABASE_URL = "rehearsal-2.db"` in PowerShell. Your existing demo stays available.

## Five-phase submission map
| Phase | Files and demonstration |
|---|---|
| 1 · Model | `docs/model.md`, `docs/er-diagram.png`, `sql/schema.sql`. Review cardinalities, keys and 3NF, then obtain your instructor's schema sign-off. |
| 2 · Procedures | `sql/gross_pay.sql`, `sql/tax_due.sql`, `sql/postgres_functions.sql`, `db.py` (trigger installation), `payroll.py` (seed and pay run). |
| 3 · Reports | `sql/attendance_report.sql`, `sql/late_report.sql`, `sql/slips.sql`, `sql/indexes.sql`, `evidence.py`, `docs/query-plan.txt`. |
| 4 · Security and tests | `app.py`, `db.py`, `test_capstone.py`, `docs/test-results.txt`. Demonstrate server-side scope, a failed batch and a competing pay run. |
| 5 · Integration | `templates/`, `static/style.css`, this README and `docs/team-and-report.md`. All pages call the same backend used in Phases 1–4. |

## Reproduce the evidence
From the project directory, run these with the Python executable in your virtual environment.
```text
python -m unittest -v test_capstone
python evidence.py
```
The suite creates fresh temporary SQLite databases. To run it on PostgreSQL, set `PAYDESK_TEST_POSTGRES` to a dedicated database URL. The suite creates a uniquely named schema per test and removes only that schema afterward. `evidence.py` compares the real late-marks query before and after its index on a disposable SQLite copy. Captured results in this package were run on SQLite. Run the PostgreSQL suite on your team machine before a PostgreSQL presentation.

## Operating assumptions
The demo uses a Monday–Friday calendar covering 2025–2035, full-day paid leave, whole-rupee monthly salaries and a fixed classroom tax formula. Missed time must be recorded as absent before HR can post a period. Upcoming and unfinished months cannot be posted. The app accepts salary revisions from the first day of a month. Salary and tax rules, reporting definitions, deployment scope and team handoff are explained in `docs/team-and-report.md`.

