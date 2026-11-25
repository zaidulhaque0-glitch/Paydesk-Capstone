SELECT e.code,e.full_name,a.work_date,a.clock_in,a.clock_in-550 AS minutes_late
FROM attendance a JOIN employee e ON e.code=a.employee_code
WHERE a.status='present' AND a.clock_in>550
  AND a.work_date>=:start AND a.work_date<:stop {{scope}}
ORDER BY a.work_date,e.code

