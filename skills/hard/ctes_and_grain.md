---
name: sql-cte-grain
description: WITH common table expressions, preaggregation, multi-stage analytics, join cardinality, and inflated totals.
---

# CTEs and aggregation grain

Preaggregate the many side before joining when the desired result has one row per customer.

```sql
WITH totals AS (
    SELECT customer_id, SUM(amount) AS total_amount
    FROM orders
    GROUP BY customer_id
)
SELECT c.id, c.name, COALESCE(t.total_amount, 0) AS total_amount
FROM customers AS c
LEFT JOIN totals AS t ON t.customer_id = c.id
ORDER BY c.id;
```

Define each CTE's row grain. CTEs must remain read-only; never hide writes in WITH. Null-to-zero replacement here assumes a customer with no orders has zero sales.
