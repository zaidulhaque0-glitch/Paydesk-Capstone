-- The primary key starts with employee_code. This second access path is for the firm-wide late report.
CREATE INDEX idx_attendance_late_date ON attendance(work_date,employee_code) WHERE status='present' AND clock_in>550;
CREATE INDEX idx_leave_employee_range ON leave_request(employee_code,start_date,end_date) WHERE status='approved';

