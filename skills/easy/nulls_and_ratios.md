---
name: sql-nulls-ratios
description: Missing NULL values, COALESCE defaults, NULLIF zero denominators, percentages, and safe division.
---

# Nulls and ratios

Use IS NULL, never = NULL. Decide whether a null means unknown or zero before using COALESCE.

```sql
SELECT region,
       SUM(COALESCE(amount, 0)) AS total_amount,
       100.0 * SUM(CASE WHEN status = 'paid' THEN 1 ELSE 0 END)
           / NULLIF(COUNT(*), 0) AS paid_percentage
FROM orders
GROUP BY region;
```

Use a decimal multiplier to avoid integer division. NULLIF preserves an undefined ratio as null instead of inventing a zero result.
