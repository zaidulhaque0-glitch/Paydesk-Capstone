-- Inputs are whole rupees. Round half up only after multiplying.
SELECT (monthly_amount * paid_days + working_days / 2) / working_days

