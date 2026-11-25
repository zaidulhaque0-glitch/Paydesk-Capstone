"""Read-only evidence collection against a fresh classroom dataset."""
from pathlib import Path
from tempfile import TemporaryDirectory
from db import Database, initialize, sql
from payroll import report


def main():
    with TemporaryDirectory() as temp:
        db=Database(str(Path(temp)/"evidence.db"))
        initialize(db)
        with db.session(write=True) as tx:
            print("Fresh seed | embedded SQLite")
            for table in ("employee","salary","attendance","leave_request","pay_period","payroll"):
                print(f"{table:16} {tx.one('SELECT COUNT(*) AS n FROM '+table)['n']}")
            print("\nSeptember attendance | first employee")
            print(report(tx,"attendance_report","2026-09")[0])
            print("\nAugust salary slip | first employee")
            print(report(tx,"slips","2026-08")[0])
            q=sql("late_report").replace("{{scope}}","")
            args={"start":"2026-09-01","stop":"2026-10-01"}
            tx.query("DROP INDEX idx_attendance_late_date")
            def trace(label):
                print("\n"+label)
                for row in tx.rows("EXPLAIN QUERY PLAN "+q,**args):
                    print("  "+row["detail"])
                steps=0
                def progress():
                    nonlocal steps
                    steps+=1
                    return 0
                tx.conn.set_progress_handler(progress,1)
                try:
                    rows=tx.rows(q,**args)
                finally:
                    tx.conn.set_progress_handler(None,0)
                print(f"  {len(rows)} late marks | {steps} SQLite VM instructions")
                return rows,steps
            before,old=trace("Before adding the attendance index")
            definition=next(s for s in sql("indexes").splitlines() if s.startswith("CREATE INDEX idx_attendance"))
            tx.query(definition)
            after,new=trace("After adding the attendance index")
            assert before==after
            print(f"\nIdentical report rows; instruction count changed by {(old-new)/old:.1%}.")

if __name__=="__main__":
    main()

