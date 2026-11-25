"""Run with python -m unittest -v. Optionally set PAYDESK_TEST_POSTGRES to a disposable database URL."""
import csv
import io
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from uuid import uuid4

from app import create_app
from db import Database, RuleError
from payroll import ADMIN, DEMO_PASS, post_payroll, report


class CapstoneTests(unittest.TestCase):
    def setUp(self):
        url=os.getenv("PAYDESK_TEST_POSTGRES")
        if url:
            import psycopg
            from psycopg import sql
            schema="paydesk_test_"+uuid4().hex
            with psycopg.connect(url,autocommit=True) as conn:
                conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            def cleanup():
                with psycopg.connect(url,autocommit=True) as conn:
                    conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            self.addCleanup(cleanup)
            parts=urlsplit(url)
            options=dict(parse_qsl(parts.query))
            options["options"]="-csearch_path="+schema
            self.db=Database(urlunsplit(parts._replace(query=urlencode(options))))
        else:
            tmp=tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            self.db=Database(str(Path(tmp.name)/"test.db"))
        self.app=create_app(self.db,testing=True)
        self.client=self.app.test_client()
        self.login(ADMIN)

    def login(self,email,password=DEMO_PASS):
        self.client.get("/login")
        return self.post("/login",email=email,password=password)

    def post(self,path,**fields):
        with self.client.session_transaction() as session:
            token=session["csrf"]
        return self.client.post(path,data={"csrf":token,**fields},follow_redirects=True)

    def test_01_all_six_screens_and_three_reports(self):
        for view in ("overview","people","attendance","leave","payroll","reports"):
            response=self.client.get("/workspace/"+view)
            self.assertEqual(response.status_code,200)
            self.assertIn(b"Paydesk",response.data)
        for kind in ("summary","late","payslips"):
            self.assertEqual(self.client.get("/workspace/reports?month=2026-08&kind="+kind).status_code,200)
            self.assertIn("text/csv",self.client.get("/export/"+kind+"?month=2026-08").content_type)

    def test_02_seed_has_12_employees_and_three_complete_months(self):
        with self.db.session() as tx:
            for m in ("2026-07","2026-08","2026-09"):
                rows=report(tx,"attendance_report",m)
                self.assertEqual(len(rows),12)
                for row in rows:
                    self.assertEqual(row["unmarked"],0)
                    self.assertEqual(row["scheduled"],row["present"]+row["absent"]+row["leave_days"])
            self.assertEqual(len(report(tx,"slips","2026-08")),12)
            self.assertEqual(report(tx,"slips","2026-09"),[])

    def test_03_payroll_math_and_tax_thresholds(self):
        with self.db.session() as tx:
            for gross,tax in [(0,0),(40000,0),(40005,1),(80000,4000),(80005,4001),(100000,8000)]:
                self.assertEqual(tx.one("SELECT tax_due(:g) AS t",g=gross)["t"],tax)
            self.assertEqual(tx.one("SELECT gross_pay(75000,21,22) AS g")["g"],71591)
            self.assertEqual(tx.one("SELECT gross_pay(75000,0,22) AS g")["g"],0)

    def test_04_salary_revision_used_only_from_effective_month(self):
        self.post("/action/pay",month="2026-09")
        with self.db.session() as tx:
            august=report(tx,"slips","2026-08","IT-001")[0]
            sept=report(tx,"slips","2026-09","IT-001")[0]
            self.assertEqual((august["monthly_amount"],sept["monthly_amount"]),(72000,75000))
            self.assertEqual(sept["net"],sept["gross"]-sept["tax"])
        self.assertIn("Salary slip",self.client.get("/payslip/IT-001?month=2026-09").text)

    def test_05_negative_salary_rolls_back_employee_and_login(self):
        r=self.post("/action/employee",month="2026-09",code="IT-099",name="Test Person",department="ENG",
                    title="Analyst",hired_on="2026-09-02",amount="-1",email="new@example.test",password="TestPass123")
        self.assertIn("Monthly salary must",r.text)
        with self.db.session() as tx:
            self.assertIsNone(tx.one("SELECT * FROM employee WHERE code='IT-099'"))
            self.assertIsNone(tx.one("SELECT * FROM app_user WHERE employee_code='IT-099'"))

    def test_06_duplicate_attendance_fails_without_overwriting(self):
        data=dict(month="2026-10",employee="IT-001",day="2026-10-01",status="present",clock_in="09:00",clock_out="17:30")
        self.assertIn("Changes saved",self.post("/action/attendance",**data).text)
        data["clock_in"]="09:20"
        self.assertIn("already exists",self.post("/action/attendance",**data).text)
        with self.db.session() as tx:
            self.assertEqual(tx.one("SELECT clock_in FROM attendance WHERE employee_code='IT-001' AND work_date='2026-10-01'")["clock_in"],540)

    def test_07_late_cutoff_and_absence(self):
        for emp,t,mode in [("IT-001","09:10","present"),("IT-002","09:11","present"),("IT-003","","absent")]:
            r=self.post("/action/attendance",employee=emp,day="2026-10-01",month="2026-10",status=mode,clock_in=t,clock_out="18:00")
            self.assertIn("Changes saved",r.text)
        with self.db.session() as tx:
            rows=report(tx,"late_report","2026-10")
            self.assertEqual([(r["code"],r["minutes_late"]) for r in rows],[("IT-002",1)])

    def test_08_approved_overlap_inclusive_and_attendance_conflict(self):
        with self.db.session() as tx:
            original=tx.one("SELECT id FROM leave_request WHERE status='pending'")["id"]
        self.assertIn("Changes saved",self.post("/action/decision",month="2026-10",id=original,state="approved").text)
        self.post("/action/leave",month="2026-10",employee="IT-003",start="2026-10-06",end="2026-10-08",kind="sick")
        with self.db.session() as tx:
            overlap=tx.one("SELECT id FROM leave_request WHERE status='pending'")["id"]
        self.assertIn("overlaps",self.post("/action/decision",month="2026-10",id=overlap,state="approved").text)
        r=self.post("/action/attendance",month="2026-10",employee="IT-003",day="2026-10-06",status="absent")
        self.assertIn("Approved leave already covers",r.text)

    def test_09_reversed_time_and_weekend_rejected(self):
        args=dict(month="2026-10",employee="IT-001",status="present",clock_in="10:10",clock_out="09:00",day="2026-10-01")
        self.assertIn("after clock-in",self.post("/action/attendance",**args).text)
        args.update(day="2026-10-03",clock_out="18:00")
        self.assertIn("working day",self.post("/action/attendance",**args).text)

    def test_10_batch_failure_after_partial_work_rolls_back(self):
        with self.db.session(write=True) as tx:
            tx.query("DELETE FROM attendance WHERE employee_code='IT-012' AND work_date='2026-09-01'")
        with self.assertRaisesRegex(RuleError,"unmarked"):
            with self.db.session(write=True) as tx:
                post_payroll(tx,"2026-09",ADMIN)
        with self.db.session() as tx:
            self.assertIsNone(tx.one("SELECT * FROM pay_period WHERE month_start='2026-09-01'"))
            self.assertEqual(report(tx,"slips","2026-09"),[])

    def test_11_repeated_and_competing_posts_leave_one_complete_batch(self):
        def post_one(_):
            try:
                with self.db.session(write=True) as tx:
                    post_payroll(tx,"2026-09",ADMIN)
                return "posted"
            except RuleError:
                return "already posted"
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(post_one,range(2))),["already posted","posted"])
        with self.db.session() as tx:
            self.assertEqual(len(report(tx,"slips","2026-09")),12)

    def test_12_posted_inputs_are_locked(self):
        data=dict(month="2026-08",employee="IT-001",day="2026-08-03",status="absent",correct="yes")
        self.assertIn("Payroll is posted",self.post("/action/attendance",**data).text)
        self.assertIn("alter posted payroll",self.post("/action/salary",month="2026-08",employee="IT-001",
                                                      effective="2026-08",amount="80000").text)

    def test_13_employee_scope_in_pages_exports_and_direct_urls(self):
        self.login("ananya@paydesk.test")
        for page in ("people","attendance","leave","payroll","overview","reports"):
            r=self.client.get("/workspace/"+page+"?month=2026-08")
            self.assertEqual(r.status_code,200)
            self.assertNotIn("Kabir Shah",r.text)
        for kind in ("summary","late","payslips"):
            r=self.client.get("/export/"+kind+"?month=2026-08&employee=IT-002")
            rows=list(csv.DictReader(io.StringIO(r.text)))
            self.assertTrue(rows)
            self.assertEqual({row["code"] for row in rows},{"IT-001"})
        self.assertEqual(self.client.get("/payslip/IT-002?month=2026-08").status_code,403)
        self.assertEqual(self.client.get("/payslip/IT-001?month=2026-08").status_code,200)
        for action in ("employee","salary","decision","pay","attendance","leave","profile"):
            self.assertEqual(self.post("/action/"+action,month="2026-09").status_code,403)

    def test_14_csrf_logged_out_and_wrong_password(self):
        self.assertEqual(self.client.post("/action/pay",data={"month":"2026-09"}).status_code,400)
        self.post("/logout")
        self.assertEqual(self.client.get("/workspace/people").status_code,302)
        self.assertIn("incorrect",self.login(ADMIN,"wrong-password").text)

    def test_15_join_midmonth_and_salary_revision(self):
        self.assertIn("Changes saved",self.post("/action/employee",month="2026-09",code="IT-099",name="New Joiner",
            department="DES",title="Designer",hired_on="2026-09-30",amount="44000",
            email="joiner@example.test",password="A-long-demo-password").text)
        self.post("/action/attendance",month="2026-09",employee="IT-099",day="2026-09-30",
                  status="present",clock_in="09:00",clock_out="17:00")
        self.post("/action/pay",month="2026-09")
        with self.db.session() as tx:
            row=report(tx,"slips","2026-09","IT-099")[0]
            self.assertEqual((row["paid_days"],row["working_days"],row["net"]),(1,22,2000))

    def test_16_approved_leave_counts_only_eligible_weekdays(self):
        self.post("/action/leave",month="2026-10",employee="IT-001",start="2026-10-02",end="2026-10-05",kind="annual")
        with self.db.session() as tx:
            key=tx.one("SELECT id FROM leave_request WHERE employee_code='IT-001' AND status='pending'")["id"]
        self.post("/action/decision",month="2026-10",id=key,state="approved")
        with self.db.session() as tx:
            row=report(tx,"attendance_report","2026-10","IT-001")[0]
            self.assertEqual((row["leave_days"],row["unmarked"]),(2,row["scheduled"]-2))

if __name__=="__main__":
    unittest.main(verbosity=2)

