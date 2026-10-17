---
name: sql-aggregation
description: GROUP BY regional totals, SUM, COUNT, AVG, HAVING, and aggregation grouping errors.
---

# Aggregation

Use WHERE for source rows and HAVING for grouped results. Every selected non-aggregate column must be grouped.

```sql
SELECT region, COUNT(*) AS order_count, SUM(amount) AS total_amount
FROM orders
WHERE amount IS NOT NULL
GROUP BY region
HAVING COUNT(*) >= 2
ORDER BY total_amount DESC, region ASC;
```

COUNT(*) counts rows; COUNT(amount) excludes null amounts. Check join duplication before interpreting totals. Do not compute a full total from a truncated preview.
