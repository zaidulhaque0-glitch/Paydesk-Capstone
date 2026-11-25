-- Classroom monthly policy: 0% up to 40k, 10% on next 40k, 20% on the balance.
SELECT (CASE WHEN gross <= 40000 THEN 0
             WHEN gross <= 80000 THEN (gross - 40000) * 10
             ELSE 400000 + (gross - 80000) * 20 END + 50) / 100

