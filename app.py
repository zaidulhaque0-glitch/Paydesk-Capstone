from datetime import date, timedelta
from secrets import compare_digest, token_hex
import csv
import io
import os
import sqlite3

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for, Response
from werkzeug.security import check_password_hash

from db import DATA, Database, RuleError, initialize, month_bounds
from payroll import ADMIN, DEMO_PASS, add_employee, add_salary, clean, mark, post_payroll, report, request_leave

DEFAULT_MONTH = "2026-09"
PAGES = {"overview":"Overview","people":"Employees","attendance":"Attendance","leave":"Leave desk",
         "payroll":"Payroll","reports":"Reports"}
REPORTS = {"summary":"attendance_report","late":"late_report","payslips":"slips"}
LABELS = {"summary":"Monthly attendance","late":"Late marks","payslips":"Salary slips"}
FIELDS = {"summary":("code","full_name","department","scheduled","present","absent","leave_days","unmarked","late"),
          "late":("code","full_name","work_date","clock_in","minutes_late"),
          "payslips":("code","full_name","month_start","monthly_amount","working_days","paid_days","gross","tax","net")}


def local_key():
    DATA.mkdir(exist_ok=True)
    path=DATA/"session.key"
    if "PAYDESK_SECRET" in os.environ:
        return os.environ["PAYDESK_SECRET"]
    try:
        with path.open("x",encoding="ascii") as f:
            f.write(token_hex(32))
    except FileExistsError:
        pass
    return path.read_text(encoding="ascii")


def create_app(database=None, testing=False):
    app=Flask(__name__)
    app.config.update(SECRET_KEY=token_hex(32) if testing else local_key(), TESTING=testing,
                      SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8),MAX_CONTENT_LENGTH=32768)
    db=database or Database()
    initialize(db)
    integrity=(sqlite3.IntegrityError,)
    if db.postgres:
        from psycopg import IntegrityError
        integrity+=(IntegrityError,)

    @app.template_filter("money")
    def money(n):
        s=str(abs(int(n)))
        tail=s[-3:]
        head=s[:-3]
        while head:
            tail=head[-2:]+","+tail
            head=head[:-2]
        return ("−" if n<0 else "")+"₹"+tail

    @app.template_filter("clock")
    def clock(n):
        return "—" if n is None else f"{n//60:02d}:{n%60:02d}"

    @app.before_request
    def prepare():
        if request.endpoint=="static":
            return
        session.setdefault("csrf",token_hex(24))
        if request.method=="POST" and not compare_digest(session["csrf"], request.form.get("csrf","")):
            abort(400,description="Session expired. Refresh the page and try again.")
        g.user=None
        if session.get("email"):
            with db.session() as tx:
                g.user=tx.one("""SELECT u.email,u.role,u.employee_code,e.full_name FROM app_user u
                    LEFT JOIN employee e ON e.code=u.employee_code WHERE u.email=:email""",email=session["email"])
        if request.endpoint not in ("login","static") and not g.user:
            return redirect(url_for("login"))

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"]="no-store"
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["X-Frame-Options"]="DENY"
        return response

    @app.route("/login",methods=["GET","POST"])
    def login():
        if request.method=="POST":
            with db.session() as tx:
                user=tx.one("SELECT * FROM app_user WHERE email=:e",e=request.form.get("email","").strip().lower())
            if user and check_password_hash(user["password_hash"],request.form.get("password","")):
                session.clear()
                session.update(email=user["email"],csrf=token_hex(24))
                session.permanent=True
                return redirect(url_for("home"))
            flash("Email or password is incorrect.","error")
        return render_template("login.html",admin=ADMIN,password=DEMO_PASS)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    def selected():
        value=request.values.get("month",DEFAULT_MONTH)
        try:
            first,stop=month_bounds(value)
        except RuleError as err:
            abort(400,description=str(err))
        return value,first,stop

    def employee_scope():
        return None if g.user["role"]=="hr" else g.user["employee_code"]

    @app.get("/")
    def home():
        return redirect(url_for("page",view="overview",month=DEFAULT_MONTH))

    @app.get("/workspace/<view>")
    def page(view):
        if view not in PAGES:
            abort(404)
        month,first,stop=selected()
        scope=employee_scope()
        params={"start":first.isoformat(),"stop":stop.isoformat()}
        own=" AND e.code=:emp" if scope else ""
        if scope:
            params["emp"]=scope
        with db.session() as tx:
            employees=tx.rows("""SELECT e.*,d.name AS department,
               (SELECT s.monthly_amount FROM salary s WHERE s.employee_code=e.code AND s.effective_month<=:start
                ORDER BY s.effective_month DESC LIMIT 1) AS rate
               FROM employee e JOIN department d ON d.code=e.department_code WHERE 1=1"""+own+" ORDER BY e.code",**params)
            summary=report(tx,"attendance_report",month,scope)
            slips=report(tx,"slips",month,scope)
            posted=bool(tx.one("SELECT 1 FROM pay_period WHERE month_start=:m",m=first.isoformat()))
            totals={k:sum(row[k] for row in summary) for k in ("scheduled","present","absent","leave_days","unmarked","late")}
            leaves=tx.rows("""SELECT l.*,e.full_name FROM leave_request l JOIN employee e ON e.code=l.employee_code
                        WHERE l.start_date<:stop AND l.end_date>=:start"""+own+" ORDER BY l.start_date DESC,e.code",**params)
            context=dict(pages=PAGES,view=view,title=PAGES[view],month=month,month_name=first.strftime("%B %Y"),
                         employees=employees,summary=summary,slips=slips,posted=posted,totals=totals,leaves=leaves,
                         total_net=sum(s["net"] for s in slips),hr=scope is None,
                         departments=tx.rows("SELECT * FROM department ORDER BY name") if scope is None else [],
                         reports=LABELS,fields=FIELDS)
            if view=="overview":
                day_rows=tx.rows("""SELECT c.work_date,COUNT(a.clock_in) AS present,COUNT(e.code) AS expected
                    FROM work_calendar c JOIN employee e ON e.hired_on<=c.work_date
                    LEFT JOIN attendance a ON a.employee_code=e.code AND a.work_date=c.work_date
                    WHERE c.work_date>=:start AND c.work_date<:stop"""+own+" GROUP BY c.work_date ORDER BY c.work_date",**params)
                groups={}
                for row in day_rows:
                    d=date.fromisoformat(str(row["work_date"]))
                    monday=d-timedelta(days=d.weekday())
                    entry=groups.setdefault(monday,[0,0,d,d])
                    entry[0]+=row["present"]
                    entry[1]+=row["expected"]
                    entry[3]=d
                context["weeks"]=[(f"{v[2].day:02d}–{v[3].day:02d}",round(100*v[0]/v[1])) for v in groups.values()]
            if view=="attendance":
                context["entries"]=tx.rows("""SELECT a.*,e.full_name FROM attendance a JOIN employee e ON e.code=a.employee_code
                    WHERE a.work_date>=:start AND a.work_date<:stop"""+own+" ORDER BY a.work_date DESC,e.code",**params)
            if view=="reports":
                kind=request.args.get("kind","summary")
                if kind not in REPORTS:
                    abort(400)
                context.update(kind=kind,records=report(tx,REPORTS[kind],month,scope))
        return render_template("workspace.html",**context)

    @app.get("/payslip/<code>")
    def payslip(code):
        month,first,_=selected()
        if employee_scope() and code!=employee_scope():
            abort(403)
        with db.session() as tx:
            items=report(tx,"slips",month,code)
        if not items:
            abort(404,description="No posted payslip for this period.")
        return render_template("slip.html",s=items[0],month=month,month_name=first.strftime("%B %Y"))

    @app.get("/export/<kind>")
    def export(kind):
        if kind not in REPORTS:
            abort(404)
        month,_,_=selected()
        with db.session() as tx:
            rows=report(tx,REPORTS[kind],month,employee_scope())
        output=io.StringIO()
        writer=csv.writer(output)
        writer.writerow(FIELDS[kind])
        for row in rows:
            values=[row[k] for k in FIELDS[kind]]
            if kind=="late":
                values[3]=clock(values[3])
            writer.writerow([("'"+v if isinstance(v,str) and v[:1] in ("=","+","-","@") else v) for v in values])
        return Response(output.getvalue(),mimetype="text/csv",
                        headers={"Content-Disposition":f"attachment; filename=paydesk-{kind}-{month}.csv"})

    destinations={"employee":"people","profile":"people","salary":"people","attendance":"attendance",
                  "leave":"leave","decision":"leave","pay":"payroll"}

    @app.post("/action/<action>")
    def mutate(action):
        if g.user["role"]!="hr":
            abort(403)
        if action not in destinations:
            abort(404)
        month,_,_=selected()
        f=request.form
        try:
            with db.session(write=True) as tx:
                if action=="employee":
                    add_employee(tx,f)
                elif action=="profile":
                    cur=tx.query("UPDATE employee SET full_name=:n,department_code=:d,job_title=:t WHERE code=:e",
                                 n=clean(f.get("name"),"Name"),d=f.get("department"),t=clean(f.get("title"),"Job title"),e=f.get("employee"))
                    if cur.rowcount!=1:
                        raise RuleError("Employee not found.")
                elif action=="salary":
                    add_salary(tx,f.get("employee"),f.get("effective"),f.get("amount"))
                elif action=="attendance":
                    mark(tx,f)
                elif action=="leave":
                    request_leave(tx,f)
                elif action=="decision":
                    state=f.get("state")
                    if state not in ("approved","rejected"):
                        raise RuleError("Choose approve or reject.")
                    cur=tx.query("UPDATE leave_request SET status=:s WHERE id=:id AND status='pending'",s=state,id=f.get("id"))
                    if cur.rowcount!=1:
                        raise RuleError("This request has already been decided or is unavailable.")
                else:
                    post_payroll(tx,month,g.user["email"])
            flash("Payroll posted. Payslips are ready." if action=="pay" else "Changes saved.","ok")
        except RuleError as err:
            flash(str(err),"error")
        except integrity as err:
            message=str(err).splitlines()[0]
            low=message.lower()
            if "unique" in low or "duplicate" in low:
                message="An entry already exists for this employee, date, code or email."
            elif "foreign key" in low:
                message="Choose a valid employee, department and working day (Monday to Friday)."
            elif "check constraint" in low or "not null" in low:
                message="The record failed validation. Check the values and date range."
            flash(message,"error")
        return redirect(url_for("page",view=destinations[action],month=month),code=303)

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    def error(err):
        return render_template("error.html",err=err),err.code
    return app


if __name__=="__main__":
    create_app().run(host="127.0.0.1",port=int(os.getenv("PAYDESK_PORT","5050")),debug=False)

