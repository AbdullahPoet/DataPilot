---
name: sql-set-operations
description: UNION ALL, UNION distinct, combining periods, duplicate rows, and compatible result column types.
---

# Set operations

UNION ALL preserves rows; UNION removes duplicates. Branches must return the same number of compatible columns.

```sql
SELECT id, amount FROM orders WHERE order_date < '2025-01-01'
UNION ALL
SELECT id, amount FROM orders WHERE order_date >= '2025-01-01'
ORDER BY id;
```

Check range overlap before combining periods. Apply final ordering to the combined result. Verify dialect/version support before choosing INTERSECT or EXCEPT.
