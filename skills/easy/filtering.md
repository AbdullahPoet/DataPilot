---
name: sql-filtering
description: SELECT columns, WHERE filters, dates, ORDER BY sorting, and LIMIT top results.
---

# Filtering and sorting

Use for selecting a bounded subset. Choose explicit columns, filter before limiting, and add a stable tie-breaker.

```sql
SELECT id, customer_id, amount
FROM orders
WHERE amount >= 100 AND order_date >= '2025-01-01'
ORDER BY amount DESC, id ASC
LIMIT 10;
```

Verify names and date types against the schema. Parenthesize mixed AND/OR conditions. Never replace a missing column with an invented identifier.
