WITH amounts AS (
 SELECT e.code,e.full_name,p.month_start,s.monthly_amount,t.working_days,p.paid_days,
        gross_pay(s.monthly_amount,p.paid_days,t.working_days) AS gross
 FROM payroll p JOIN employee e ON e.code=p.employee_code
 JOIN pay_period t ON t.month_start=p.month_start
 JOIN salary s ON s.employee_code=p.employee_code AND s.effective_month=p.salary_from
 WHERE p.month_start=:start {{scope}}
)
SELECT amounts.*, tax_due(gross) AS tax, gross-tax_due(gross) AS net FROM amounts ORDER BY code

