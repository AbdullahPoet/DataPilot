---
name: sql-joins
description: INNER JOIN, LEFT JOIN, customer orders, ambiguous columns, missing relationships, and duplicate totals.
---

# Joins

Join only on verified relationships. Qualify shared column names with table aliases.

```sql
SELECT c.id, c.name, COUNT(o.id) AS order_count
FROM customers AS c
LEFT JOIN orders AS o ON o.customer_id = c.id
GROUP BY c.id, c.name
ORDER BY c.id;
```

COUNT(o.id) preserves zero orders for unmatched customers. A right-table filter in WHERE can remove unmatched rows; place it in ON when preserving them is intended. Check one-to-many multiplication before summing.
