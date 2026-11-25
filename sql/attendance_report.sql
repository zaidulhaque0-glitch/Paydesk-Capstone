-- One row per eligible employee; an unmarked weekday stays visible even if the month is empty.
WITH daily AS (
 SELECT e.code, e.full_name, d.name AS department, c.work_date,
        a.status, a.clock_in,
        CASE WHEN EXISTS (
          SELECT 1 FROM leave_request l WHERE l.employee_code=e.code AND l.status='approved'
          AND c.work_date BETWEEN l.start_date AND l.end_date
        ) THEN 1 ELSE 0 END AS on_leave
 FROM employee e JOIN department d ON d.code=e.department_code
 JOIN work_calendar c ON c.work_date>=e.hired_on
 LEFT JOIN attendance a ON a.employee_code=e.code AND a.work_date=c.work_date
 WHERE c.work_date>=:start AND c.work_date<:stop {{scope}}
)
SELECT code, full_name, department, COUNT(*) AS scheduled,
 SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) AS present,
 SUM(CASE WHEN status='absent' THEN 1 ELSE 0 END) AS absent,
 SUM(on_leave) AS leave_days,
 SUM(CASE WHEN status IS NULL AND on_leave=0 THEN 1 ELSE 0 END) AS unmarked,
 SUM(CASE WHEN clock_in>550 THEN 1 ELSE 0 END) AS late
FROM daily GROUP BY code,full_name,department ORDER BY code

