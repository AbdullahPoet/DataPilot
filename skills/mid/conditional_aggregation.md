---
name: sql-conditional-aggregation
description: CASE WHEN conditional counts, pivot-style totals, paid versus pending comparisons, and conditional sums.
---

# Conditional aggregation

Use CASE inside aggregates for portable conditional summaries without extra joins.

```sql
SELECT region,
       SUM(CASE WHEN status = 'paid' THEN amount ELSE 0 END) AS paid_amount,
       SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_count
FROM orders
GROUP BY region
ORDER BY region;
```

Confirm actual status values before using them. Keep the grouping grain consistent. An unknown category is missing source information; this example does not establish that it exists.
