---
name: sql-repair-checklist
description: Retry diagnostics for missing column, missing table, ambiguous column, SQL syntax error, grouping error, and aggregation error.
---

# Repair checklist

- Missing table/column: recheck the verified schema; references cannot supply absent identifiers.
- Ambiguous column: qualify it with the correct alias.
- Grouping error: group every selected non-aggregate expression or move aggregation to a CTE.
- Duplicate totals: inspect join cardinality and preaggregate at the intended grain.
- Syntax/version mismatch: use supported syntax for the selected dialect.

```sql
SELECT o.region, SUM(o.amount) AS total_amount
FROM orders AS o
GROUP BY o.region;
```

Make the smallest justified correction. Revalidate each candidate and respect approval and the retry limit. Never repair permission, connection, or timeout failures by changing SQL or weakening safeguards. Missing data or unclear intent requires clarification.
