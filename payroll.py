from datetime import date
from uuid import uuid4
import re
from werkzeug.security import generate_password_hash
from db import FIRST, LIMIT, RuleError, dates, month_bounds, sql

ADMIN = "hr@paydesk.test"
DEMO_PASS = "CampusDemo26!"
SAMPLE = [
    ("Ananya Rao","ENG","Software Engineer",72000), ("Kabir Shah","ENG","Platform Engineer",94000),
    ("Meera Nair","DES","Product Designer",68000), ("Arjun Iyer","OPS","Systems Analyst",56000),
    ("Isha Patel","PEO","People Partner",60000), ("Dev Menon","ENG","QA Engineer",52000),
    ("Riya Sen","DES","UX Researcher",65000), ("Neel Verma","OPS","Support Engineer",38000),
    ("Tara Joshi","ENG","Engineering Lead",125000), ("Vihaan Das","OPS","Data Analyst",74000),
    ("Sana Ali","PEO","HR Associate",42000), ("Ishaan Roy","ENG","Backend Engineer",81000)
]


def report(tx, name, month, employee=None):
    first, stop = month_bounds(month)
    predicate = "AND e.code=:employee" if employee else ""
    params = {"start": first.isoformat()}
    if name != "slips":
        params["stop"] = stop.isoformat()
    if employee:
        params["employee"] = employee
    return tx.rows(sql(name).replace("{{scope}}", predicate), **params)


def post_payroll(tx, month, actor, *, today=None):
    first, stop = month_bounds(month)
    if first >= (today or date.today()).replace(day=1):
        raise RuleError("Payroll can be posted after the month has ended.")
    if tx.one("SELECT 1 FROM pay_period WHERE month_start=:d", d=first.isoformat()):
        raise RuleError("This month has already been posted.")
    summary = report(tx, "attendance_report", month)
    if not summary:
        raise RuleError("No eligible employees in this period.")
    count = tx.one("SELECT COUNT(*) AS n FROM work_calendar WHERE work_date>=:a AND work_date<:b",
                   a=first.isoformat(), b=stop.isoformat())["n"]
    tx.query("INSERT INTO pay_period VALUES (:m,:n,:u)",m=first.isoformat(),n=count,u=actor)
    for row in summary:
        if row["unmarked"]:
            raise RuleError(f"{row['full_name']} has {row['unmarked']} unmarked workdays.")
        salary = tx.one("""SELECT effective_month FROM salary WHERE employee_code=:e AND effective_month<=:m
                         ORDER BY effective_month DESC LIMIT 1""",e=row["code"],m=first.isoformat())
        if not salary:
            raise RuleError(f"Missing salary for {row['full_name']}.")
        tx.query("INSERT INTO payroll VALUES (:e,:m,:s,:p)", e=row["code"], m=first.isoformat(),
                 s=salary["effective_month"],p=row["present"] + row["leave_days"])
    return len(summary)


def clean(value, label, limit=80):
    value = (value or "").strip()
    if not 1 <= len(value) <= limit:
        raise RuleError(f"{label} must be between 1 and {limit} characters.")
    return value


def valid_date(value):
    try:
        d = date.fromisoformat(value)
    except (TypeError,ValueError):
        raise RuleError("Enter a valid calendar date.") from None
    if not FIRST <= d < LIMIT or d.isoformat() != value:
        raise RuleError("Dates must be within the 2025–2035 work calendar.")
    return value


def minutes(value):
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",value or ""):
        raise RuleError("Enter both clock times in 24-hour format.")
    h, m = map(int,value.split(":"))
    return h * 60 + m


def add_employee(tx, form):
    code = clean(form.get("code"),"Employee code",12).upper()
    if not re.fullmatch(r"[A-Z0-9-]{2,12}",code):
        raise RuleError("Use 2–12 letters, digits or hyphens for the employee code.")
    hired = valid_date(form.get("hired_on"))
    email = clean(form.get("email"),"Email",180).lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email):
        raise RuleError("Enter a valid login email.")
    password = form.get("password","")
    if not 10 <= len(password) <= 128:
        raise RuleError("Choose a password between 10 and 128 characters.")
    tx.query("INSERT INTO employee VALUES (:c,:n,:d,:j,:h)",c=code,n=clean(form.get("name"),"Name"),
             d=form.get("department"),j=clean(form.get("title"),"Job title"),h=hired)
    add_salary(tx,code,hired[:7],form.get("amount"))
    tx.query("INSERT INTO app_user VALUES (:m,:p,'employee',:e)",m=email,p=generate_password_hash(password),e=code)


def add_salary(tx, code, month, value):
    first, _ = month_bounds(month)
    try:
        amount = int(value)
    except (TypeError,ValueError):
        raise RuleError("Enter a whole-rupee salary.") from None
    if not 1<=amount<=10000000:
        raise RuleError("Monthly salary must be ₹1 to ₹1,00,00,000.")
    tx.query("INSERT INTO salary VALUES (:e,:m,:a)",e=code,m=first.isoformat(),a=amount)


def mark(tx, form):
    day = valid_date(form.get("day"))
    status = form.get("status")
    ci = minutes(form.get("clock_in")) if status=="present" else None
    co = minutes(form.get("clock_out")) if status=="present" else None
    if ci is not None and co<=ci:
        raise RuleError("Clock-out must be after clock-in.")
    params=dict(e=form.get("employee"),d=day,s=status,i=ci,o=co)
    if form.get("correct")=="yes":
        cur=tx.query("""UPDATE attendance SET status=:s,clock_in=:i,clock_out=:o
                        WHERE employee_code=:e AND work_date=:d""",**params)
        if cur.rowcount!=1:
            raise RuleError("No existing entry to correct.")
    else:
        tx.query("INSERT INTO attendance VALUES (:e,:d,:s,:i,:o)",**params)


def request_leave(tx, form):
    start,end = valid_date(form.get("start")),valid_date(form.get("end"))
    tx.query("INSERT INTO leave_request VALUES (:id,:e,:a,:b,:k,'pending')",
             id=uuid4().hex,e=form.get("employee"),a=start,b=end,k=form.get("kind"))


def seed(tx):
    for code,name in [("ENG","Engineering"),("DES","Design"),("OPS","IT Operations"),("PEO","People")]:
        tx.query("INSERT INTO department VALUES (:c,:n)",c=code,n=name)
    # Bulk-insert thousands of weekdays without individual database round trips.
    calendar = [(d.isoformat(),) for d in dates(FIRST,LIMIT)]
    marker = "%s" if tx.postgres else "?"
    with_cursor = tx.conn.cursor()
    with_cursor.executemany("INSERT INTO work_calendar VALUES ("+marker+")",calendar)
    with_cursor.close()
    password = generate_password_hash(DEMO_PASS)
    tx.query("INSERT INTO app_user VALUES (:u,:p,'hr',NULL)",u=ADMIN,p=password)
    for number,(name,dept,title,amount) in enumerate(SAMPLE,1):
        code=f"IT-{number:03d}"
        tx.query("INSERT INTO employee VALUES (:c,:n,:d,:j,'2025-07-01')",c=code,n=name,d=dept,j=title)
        tx.query("INSERT INTO salary VALUES (:c,'2025-07-01',:a)",c=code,a=amount)
        tx.query("INSERT INTO app_user VALUES (:e,:p,'employee',:c)",e=name.split()[0].lower()+"@paydesk.test",p=password,c=code)
        for month in ("2026-07","2026-08","2026-09"):
            first,stop=month_bounds(month)
            days=list(dates(first,stop))
            leave_day=days[(number*3+first.month)%len(days)]
            if number%3!=0:
                tx.query("INSERT INTO leave_request VALUES (:id,:e,:d,:d,'annual','approved')",
                         id=uuid4().hex,e=code,d=leave_day.isoformat())
            for i,day in enumerate(days):
                if number%3!=0 and day==leave_day:
                    continue
                absent=(i+number*7+first.month)%31==0
                clock = 555+(number+i)%22 if (i+2*number+first.month)%6==0 else 532+(i+number)%19
                tx.query("INSERT INTO attendance VALUES (:e,:d,:s,:i,:o)",e=code,d=day.isoformat(),
                         s="absent" if absent else "present",i=None if absent else clock,o=None if absent else clock+486)
    tx.query("INSERT INTO salary VALUES ('IT-001','2026-09-01',75000)")
    tx.query("INSERT INTO leave_request VALUES (:id,'IT-003','2026-10-05','2026-10-06','personal','pending')",id=uuid4().hex)
    for month in ("2026-07","2026-08"):
        post_payroll(tx,month,ADMIN,today=date(2026,11,1))

