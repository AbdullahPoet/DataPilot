---
name: sql-subqueries-exists
description: Correlated subqueries, EXISTS, NOT EXISTS, anti joins, customers without orders, and null-safe exclusions.
---

# Existence and exclusion

Use EXISTS when only the presence of related rows matters. Prefer NOT EXISTS over NOT IN when the subquery can contain nulls.

```sql
SELECT c.id, c.name
FROM customers AS c
WHERE NOT EXISTS (
    SELECT 1 FROM orders AS o WHERE o.customer_id = c.id
)
ORDER BY c.id;
```

Correlate the correct outer key. A scalar subquery must return at most one row. Missing relationship metadata requires clarification, not a guessed join.
