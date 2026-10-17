---
name: verified-aggregation
description: Sum, count, average, and group totals using verified source columns.
---

Use only tables and columns in the verified schema or file profile. Determine the requested grouping and measure before selecting an aggregation. Preserve null groups when appropriate and state assumptions about missing values. Do not infer a total from a truncated result. For SQL use one read-only SELECT. For files describe steps that compile to the supported groupby, filter, select, sort, and limit operations. Keep analysis within the current session and source.
