---
name: sql-window-ranking
description: Window functions, ROW_NUMBER top per group, ranking ties, running totals, and latest customer orders.
---

# Window functions

Use a CTE to filter window results portably. ROW_NUMBER chooses one row; RANK can preserve ties.

```sql
WITH ranked AS (
    SELECT id, customer_id, amount,
           ROW_NUMBER() OVER (
               PARTITION BY customer_id ORDER BY order_date DESC, id DESC
           ) AS rn
    FROM orders
)
SELECT id, customer_id, amount FROM ranked WHERE rn = 1;
```

For running totals, specify ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW. Require a supported database version; MySQL needs version 8 or newer for this pattern.
