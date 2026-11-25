-- The initializer substitutes the two adjacent, version-controlled SELECT bodies.
CREATE FUNCTION gross_pay(monthly_amount integer, paid_days integer, working_days integer)
RETURNS integer LANGUAGE sql IMMUTABLE STRICT AS $$ {{gross_pay}} $$;
CREATE FUNCTION tax_due(gross integer)
RETURNS integer LANGUAGE sql IMMUTABLE STRICT AS $$ {{tax_due}} $$;

