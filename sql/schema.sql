-- The same Phase 1 DDL is installed on both engines. Dates are ISO dates.
CREATE TABLE department (
    code VARCHAR(12) PRIMARY KEY NOT NULL,
    name VARCHAR(80) NOT NULL UNIQUE
);
CREATE TABLE employee (
    code VARCHAR(12) PRIMARY KEY NOT NULL,
    full_name VARCHAR(80) NOT NULL CHECK(length(trim(full_name)) BETWEEN 1 AND 80),
    department_code VARCHAR(12) NOT NULL REFERENCES department(code),
    job_title VARCHAR(80) NOT NULL CHECK(length(trim(job_title)) BETWEEN 1 AND 80),
    hired_on DATE NOT NULL
);
CREATE TABLE app_user (
    email VARCHAR(180) PRIMARY KEY NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(10) NOT NULL CHECK(role IN ('hr','employee')),
    employee_code VARCHAR(12) UNIQUE REFERENCES employee(code),
    CHECK ((role='hr' AND employee_code IS NULL) OR (role='employee' AND employee_code IS NOT NULL))
);
CREATE TABLE work_calendar (
    work_date DATE PRIMARY KEY NOT NULL
);
CREATE TABLE salary (
    employee_code VARCHAR(12) NOT NULL REFERENCES employee(code),
    effective_month DATE NOT NULL,
    monthly_amount INTEGER NOT NULL CHECK(monthly_amount BETWEEN 1 AND 10000000),
    PRIMARY KEY(employee_code,effective_month)
);
-- Presence uses clock times in minutes after midnight. Missing entries and explicit absence differ.
CREATE TABLE attendance (
    employee_code VARCHAR(12) NOT NULL REFERENCES employee(code),
    work_date DATE NOT NULL REFERENCES work_calendar(work_date),
    status VARCHAR(8) NOT NULL CHECK(status IN ('present','absent')),
    clock_in INTEGER,
    clock_out INTEGER,
    PRIMARY KEY(employee_code,work_date),
    CHECK ((status='absent' AND clock_in IS NULL AND clock_out IS NULL) OR
           (status='present' AND clock_in IS NOT NULL AND clock_out IS NOT NULL AND
            clock_in BETWEEN 0 AND 1438 AND clock_out BETWEEN clock_in+1 AND 1439))
);
CREATE TABLE leave_request (
    id VARCHAR(32) PRIMARY KEY NOT NULL,
    employee_code VARCHAR(12) NOT NULL REFERENCES employee(code),
    start_date DATE NOT NULL, end_date DATE NOT NULL,
    kind VARCHAR(12) NOT NULL CHECK(kind IN ('annual','sick','personal')),
    status VARCHAR(10) NOT NULL CHECK(status IN ('pending','approved','rejected')),
    CHECK(end_date >= start_date)
);
-- A period row represents a posted batch. Its creation and every payslip are one transaction.
CREATE TABLE pay_period (
    month_start DATE PRIMARY KEY NOT NULL,
    working_days INTEGER NOT NULL CHECK(working_days BETWEEN 1 AND 31),
    posted_by VARCHAR(180) NOT NULL REFERENCES app_user(email)
);
CREATE TABLE payroll (
    employee_code VARCHAR(12) NOT NULL,
    month_start DATE NOT NULL REFERENCES pay_period(month_start),
    salary_from DATE NOT NULL,
    paid_days INTEGER NOT NULL CHECK(paid_days BETWEEN 0 AND 31),
    PRIMARY KEY(employee_code,month_start),
    FOREIGN KEY(employee_code,salary_from) REFERENCES salary(employee_code,effective_month)
);

