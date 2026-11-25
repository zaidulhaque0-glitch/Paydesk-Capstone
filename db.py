from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
import os
import re
import sqlite3

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "instance"
SQL = ROOT / "sql"
FIRST = date(2025, 1, 1)
LIMIT = date(2036, 1, 1)


class RuleError(ValueError):
    pass


def sql(name):
    return (SQL / (name + ".sql")).read_text(encoding="utf-8")


def month_bounds(value):
    try:
        first = date.fromisoformat(value + "-01")
    except (ValueError, TypeError):
        raise RuleError("Choose a valid month.") from None
    if not FIRST <= first < LIMIT:
        raise RuleError("Choose a month between January 2025 and December 2035.")
    return first, (first.replace(day=28) + timedelta(days=4)).replace(day=1)


def dates(first, stop):
    while first < stop:
        if first.weekday() < 5:
            yield first
        first += timedelta(days=1)


class Database:
    def __init__(self, url=None):
        self.url = url or os.getenv("PAYDESK_DATABASE_URL") or str(DATA / "paydesk.db")
        self.postgres = self.url.startswith(("postgresql://", "postgres://"))

    def connect(self):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            return psycopg.connect(self.url, row_factory=dict_row)
        Path(self.url).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.url, isolation_level=None, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        # SQLite has no CREATE FUNCTION DDL. Reuse PostgreSQL's exact SQL expressions.
        for name, args in [("gross_pay", ["monthly_amount", "paid_days", "working_days"]),
                           ("tax_due", ["gross"])]:
            body = sql(name)
            for arg in args:
                body = re.sub(r"\b" + arg + r"\b", ":" + arg, body)
            def evaluate(*values, query=body, names=args):
                return conn.execute(query, dict(zip(names, values))).fetchone()[0]
            conn.create_function(name, len(args), evaluate, deterministic=True)
        return conn

    @contextmanager
    def session(self, write=False):
        conn = self.connect()
        try:
            if self.postgres:
                if write:
                    # Shared by every mutation including initialization and pay runs.
                    conn.execute("SELECT pg_advisory_xact_lock(47899142)")
                else:
                    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            else:
                conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield Session(conn, self.postgres)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


class Session:
    def __init__(self, conn, postgres):
        self.conn, self.postgres = conn, postgres

    def query(self, statement, **params):
        if self.postgres:
            statement = re.sub(r"(?<!:):([a-zA-Z_]\w*)", r"%(\1)s", statement)
        return self.conn.execute(statement, params) if params else self.conn.execute(statement)

    def rows(self, statement, **params):
        return [dict(row) for row in self.query(statement, **params).fetchall()]

    def one(self, statement, **params):
        row = self.query(statement, **params).fetchone()
        return dict(row) if row else None

    def script(self, source):
        # sqlite3.executescript implicitly commits: split complete DDL without exiting the transaction.
        if self.postgres:
            self.conn.execute(source)
        else:
            unit = ""
            for line in source.splitlines(True):
                unit += line
                if sqlite3.complete_statement(unit):
                    self.conn.execute(unit)
                    unit = ""


def install_guards(tx):
    # These predicates generate equivalent native triggers on both backends.
    def guard(name, table, event, condition, message):
        ref = "OLD" if event == "DELETE" else "NEW"
        if tx.postgres:
            tx.conn.execute(f"""CREATE FUNCTION guard_{name}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF {condition} THEN RAISE EXCEPTION '{message}' USING ERRCODE='23514'; END IF;
                RETURN {ref}; END; $$""")
            tx.conn.execute(f"CREATE TRIGGER {name} BEFORE {event} ON {table} FOR EACH ROW EXECUTE FUNCTION guard_{name}()")
        else:
            tx.conn.execute(f"""CREATE TRIGGER {name} BEFORE {event} ON {table}
                FOR EACH ROW WHEN {condition} BEGIN SELECT RAISE(ABORT,'{message}'); END""")

    datepart = lambda expr: f"substr(CAST({expr} AS text),1,7)"
    def posted(expr):
        return f"EXISTS(SELECT 1 FROM pay_period p WHERE {datepart('p.month_start')}={datepart(expr)})"

    for event in ("INSERT", "UPDATE"):
        suffix = event.lower()
        old = " OR " + posted("OLD.work_date") if event == "UPDATE" else ""
        guard("att_freeze_"+suffix, "attendance", event, posted("NEW.work_date")+old, "Payroll is posted for this month.")
        guard("att_start_"+suffix, "attendance", event,
              "NEW.work_date < (SELECT hired_on FROM employee WHERE code=NEW.employee_code)", "Attendance predates joining.")
        guard("att_leave_"+suffix, "attendance", event,
              """EXISTS(SELECT 1 FROM leave_request l WHERE l.employee_code=NEW.employee_code
              AND l.status='approved' AND NEW.work_date BETWEEN l.start_date AND l.end_date)""",
              "Approved leave already covers this date.")
        guard("leave_overlap_"+suffix, "leave_request", event,
              """NEW.status='approved' AND EXISTS(SELECT 1 FROM leave_request l WHERE l.id<>NEW.id
              AND l.employee_code=NEW.employee_code AND l.status='approved'
              AND l.start_date<=NEW.end_date AND l.end_date>=NEW.start_date)""", "Approved leave overlaps an existing approval.")
        guard("leave_att_"+suffix, "leave_request", event,
              """NEW.status='approved' AND EXISTS(SELECT 1 FROM attendance a WHERE a.employee_code=NEW.employee_code
              AND a.work_date BETWEEN NEW.start_date AND NEW.end_date)""", "Attendance already exists within this leave.")
        guard("leave_dates_"+suffix, "leave_request", event,
              """NEW.start_date < (SELECT hired_on FROM employee WHERE code=NEW.employee_code)
              OR NOT EXISTS(SELECT 1 FROM work_calendar WHERE work_date BETWEEN NEW.start_date AND NEW.end_date)""",
              "Leave must include a workday after joining.")
        def closed_leave(prefix):
            return (f"({prefix}.status='approved' AND EXISTS(SELECT 1 FROM pay_period p WHERE " +
                    datepart("p.month_start")+" BETWEEN "+datepart(prefix+".start_date")+" AND "+datepart(prefix+".end_date")+"))")
        guard("leave_freeze_"+suffix,"leave_request",event,
              closed_leave("NEW")+(" OR "+closed_leave("OLD") if event=="UPDATE" else ""), "Payroll is posted for this leave period.")
        guard("salary_month_"+suffix, "salary",event,"substr(CAST(NEW.effective_month AS text),9,2)<>'01'",
              "Salary must start on the first day of a month.")
        guard("salary_freeze_"+suffix, "salary",event,
              """EXISTS(SELECT 1 FROM payroll WHERE employee_code=NEW.employee_code AND month_start>=NEW.effective_month)""",
              "Salary revision would alter posted payroll.")
    guard("att_del","attendance","DELETE",posted("OLD.work_date"),"Posted attendance is locked.")
    guard("leave_del","leave_request","DELETE",closed_leave("OLD"),"Posted leave is locked.")
    guard("emp_start","employee","INSERT",
          f"EXISTS(SELECT 1 FROM pay_period p WHERE {datepart('NEW.hired_on')}<={datepart('p.month_start')})",
          "Joining date falls within or before a posted period.")
    guard("emp_hire_lock","employee","UPDATE","NEW.hired_on<>OLD.hired_on OR NEW.code<>OLD.code",
          "Joining date and employee code are fixed.")
    for table in ("payroll","pay_period"):
        for event in ("UPDATE","DELETE"):
            guard("fixed_"+table+"_"+event.lower(),table,event,"1=1","Posted payroll is locked.")


def initialize(db):
    from payroll import seed
    with db.session(write=True) as tx:
        exists = ("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='employee'"
                  if tx.postgres else "SELECT 1 FROM sqlite_master WHERE type='table' AND name='employee'")
        if tx.one(exists):
            return
        tx.script(sql("schema"))
        if tx.postgres:
            source = sql("postgres_functions")
            for name in ("tax_due","gross_pay"):
                source = source.replace("{{"+name+"}}",sql(name).strip()+"\n")
            tx.script(source)
        tx.script(sql("indexes"))
        install_guards(tx)
        seed(tx)

