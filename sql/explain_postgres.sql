-- Run on the dedicated classroom database after initializing Paydesk.

-- Both measurements use the live report SQL and the same data. ROLLBACK restores the index.

BEGIN;

ANALYZE attendance;

ANALYZE employee;

DROP INDEX idx_attendance_late_date;

EXPLAIN (ANALYZE, BUFFERS)
SELECT e.code,e.full_name,a.work_date,a.clock_in,a.clock_in-550 AS minutes_late
FROM attendance a JOIN employee e ON e.code=a.employee_code
WHERE a.status='present' AND a.clock_in>550
  AND a.work_date>=DATE '2026-09-01' AND a.work_date<DATE '2026-10-01' 
ORDER BY a.work_date,e.code;

CREATE INDEX idx_attendance_late_date ON attendance(work_date,employee_code) WHERE status='present' AND clock_in>550;

EXPLAIN (ANALYZE, BUFFERS)
SELECT e.code,e.full_name,a.work_date,a.clock_in,a.clock_in-550 AS minutes_late
FROM attendance a JOIN employee e ON e.code=a.employee_code
WHERE a.status='present' AND a.clock_in>550
  AND a.work_date>=DATE '2026-09-01' AND a.work_date<DATE '2026-10-01' 
ORDER BY a.work_date,e.code;

ROLLBACK;
