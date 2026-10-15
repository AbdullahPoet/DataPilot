---
name: sql-foundations
description: Compact SQL fundamentals with correct examples for small language models; load when essential SQL knowledge is missing.
---

# SQL Foundations: Practical Reference

Use only verified schema identifiers. Treat examples as patterns, not actual tables. Prefer read-only `SELECT` statements. Never invent tables, columns, keys, or relationships. If the schema is incomplete, ask for clarification instead of guessing. This reference supplements, but does not replace, database validation and authorization.

## Example schema

```sql
customers(customer_id, name, city)
orders(order_id, customer_id, ordered_at, amount, status)
products(product_id, product_name, price)
order_items(order_id, product_id, quantity)
```

The lines above describe columns, **not executable DDL**. Assume `orders.customer_id → customers.customer_id`, `order_items.order_id → orders.order_id`, and `order_items.product_id → products.product_id` **only for these examples**. Use actual declared foreign keys in real queries.

## 1. SELECT, aliases, DISTINCT, limiting

```sql
SELECT customer_id, name AS customer_name FROM customers;
SELECT DISTINCT city FROM customers;
SELECT order_id, amount FROM orders ORDER BY amount DESC LIMIT 10;
```

Use `LIMIT` in SQLite, PostgreSQL, and MySQL. `SELECT *` is convenient for exploration but explicit columns are preferable. SQL result order is unspecified without `ORDER BY`.

## 2. WHERE, operators, pattern matching, NULL

```sql
SELECT * FROM orders WHERE amount >= 100 AND status = 'paid';
SELECT * FROM customers WHERE city IN ('Dhaka', 'Montreal');
SELECT * FROM customers WHERE name LIKE 'A%';
SELECT * FROM orders WHERE status IS NULL;
SELECT * FROM orders WHERE amount BETWEEN 50 AND 200;
```

`BETWEEN` includes both endpoints. `NULL` means unknown/missing; use `IS NULL` / `IS NOT NULL`, never `= NULL`. `LIKE` case sensitivity is dialect/collation dependent. `AND` binds more tightly than `OR`; use parentheses when combining them.

## 3. Aggregation, GROUP BY, HAVING

```sql
SELECT customer_id, COUNT(*) AS order_count, SUM(amount) AS revenue,
       AVG(amount) AS avg_order
FROM orders
WHERE status = 'paid'
GROUP BY customer_id
HAVING COUNT(*) >= 2
ORDER BY revenue DESC;
```

`WHERE` filters rows before grouping; `HAVING` filters groups after aggregation. Other aggregates: `MIN`, `MAX`. `COUNT(*)` counts rows; `COUNT(column)` excludes NULLs; `COUNT(DISTINCT column)` counts distinct non-NULL values. Nonaggregated selected columns generally must appear in `GROUP BY`.

## 4. Joins (only on verified relationships)

```sql
SELECT c.name, o.order_id, o.amount
FROM customers AS c
INNER JOIN orders AS o ON o.customer_id = c.customer_id;

SELECT c.name, COUNT(o.order_id) AS orders_count
FROM customers AS c
LEFT JOIN orders AS o ON o.customer_id = c.customer_id
GROUP BY c.customer_id, c.name;
```

`INNER JOIN` returns matches; `LEFT JOIN` keeps every left row and fills unmatched right fields with NULL. SQLite/MySQL do not uniformly support `FULL OUTER JOIN`; avoid without verified dialect support. Joining one-to-many tables can multiply rows and inflate totals. For left joins, place filters on the right table in `ON` if unmatched left rows must remain.

## 5. Subqueries, EXISTS, CTEs

```sql
SELECT name FROM customers
WHERE customer_id IN (SELECT customer_id FROM orders WHERE amount > 500);

SELECT c.name FROM customers AS c
WHERE EXISTS (SELECT 1 FROM orders AS o WHERE o.customer_id = c.customer_id);

WITH paid_totals AS (
    SELECT customer_id, SUM(amount) AS total
    FROM orders WHERE status = 'paid' GROUP BY customer_id
)
SELECT customer_id, total FROM paid_totals WHERE total > 1000;
```

`EXISTS` tests whether matching rows exist; correlated subqueries reference an outer query. CTEs (`WITH`) improve clarity and may or may not be materialized depending on database/optimizer.

## 6. Window functions

```sql
SELECT customer_id, ordered_at, amount,
       ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY ordered_at, order_id) AS seq,
       SUM(amount) OVER (PARTITION BY customer_id) AS customer_total
FROM orders;

SELECT customer_id, amount,
       RANK() OVER (ORDER BY amount DESC) AS amount_rank
FROM orders;
```

Window functions preserve individual rows; `GROUP BY` collapses groups. `ROW_NUMBER` assigns unique sequential positions; `RANK` leaves gaps for ties; `DENSE_RANK` does not. Use stable tie-breaking columns for repeatable ordering.

## 7. CASE, COALESCE, NULLIF, arithmetic

```sql
SELECT order_id,
       CASE WHEN amount >= 500 THEN 'high' ELSE 'regular' END AS tier,
       COALESCE(status, 'unknown') AS normalized_status
FROM orders;

SELECT customer_id, SUM(amount) / NULLIF(COUNT(*), 0) AS average_amount
FROM orders GROUP BY customer_id;
```

`CASE` expresses conditional logic; `COALESCE` returns the first non-NULL value; `NULLIF(x, 0)` avoids division by zero by producing NULL. Beware integer division; cast to an appropriate numeric type where needed.

## 8. Dates and dialect differences

```sql
-- PostgreSQL: monthly revenue
SELECT DATE_TRUNC('month', ordered_at) AS month, SUM(amount) AS revenue
FROM orders GROUP BY 1 ORDER BY 1;

-- SQLite: monthly revenue (ISO-formatted dates)
SELECT strftime('%Y-%m', ordered_at) AS month, SUM(amount) AS revenue
FROM orders GROUP BY 1 ORDER BY 1;

-- MySQL: monthly revenue
SELECT DATE_FORMAT(ordered_at, '%Y-%m') AS month, SUM(amount) AS revenue
FROM orders GROUP BY 1 ORDER BY 1;
```

Use the selected database dialect. Date storage, time zones, and function behavior differ; filter timestamp ranges with explicit boundaries when possible. Parameter syntax also depends on the driver, not only the database dialect.

## 9. Parameterized queries and safe access

```python
cursor.execute("SELECT * FROM orders WHERE customer_id = ?", (customer_id,))
```

The Python snippet above illustrates SQLite DB-API parameter binding; SQLAlchemy can use `text("... WHERE customer_id = :customer_id")` with `{"customer_id": customer_id}`. Never concatenate untrusted values into SQL. Bind values, **not identifiers** (table/column names); identifiers must come from an allowlisted verified schema. Use the application's AST read-only validator, approval gate, restricted DB account, and execution timeout. Do not produce DDL/DML, file-access functions, or multiple statements for analysis queries.

## 10. Typical SQL evaluation order and pitfalls

Logical order: `FROM`/`JOIN` → `WHERE` → `GROUP BY` → `HAVING` → window expressions / `SELECT` → `DISTINCT` → `ORDER BY` → `LIMIT` (actual optimizer execution may differ).

- Missing table/column: inspect the **verified schema**; never guess a name.
- Ambiguous column: qualify with an alias, e.g. `o.customer_id`.
- Incorrect totals after joins: check one-to-many cardinality; aggregate before joining if needed.
- Unexpected missing rows: inspect `INNER` vs `LEFT JOIN` and NULL handling.
- Unexpected order: specify `ORDER BY`; include tie-breakers.
- No rows: check predicates, types, timezone boundaries, and whether data exists.
- Query executes but answers the wrong question: compare output to the user's metric definition, grain, filters, and expected business logic.

## 11. Tiny end-to-end example

Question: "Top three customers by paid order revenue."

```sql
SELECT c.customer_id, c.name, SUM(o.amount) AS paid_revenue
FROM customers AS c
JOIN orders AS o ON o.customer_id = c.customer_id
WHERE o.status = 'paid'
GROUP BY c.customer_id, c.name
ORDER BY paid_revenue DESC, c.customer_id ASC
LIMIT 3;
```

Reasoning: join through the verified foreign key, filter paid orders, group by customer, sum order amounts, sort descending, then limit. **Check:** `orders.amount` must actually represent the intended revenue measure; otherwise use the verified line-item pricing definition.

## Response protocol for small models

If unsure how to form a SQL query, output a structured `needs_basic_knowledge` status instead of inventing syntax or schema. After loading this reference, attempt SQL generation again **once**; if still uncertain, state the blocker. Every generated query still requires AST validation, user approval when applicable, and database-level read-only execution.
