# SQL reference skills

These concise, read-only patterns are shared across models. Example identifiers are fictional: always use the verified source schema and selected SQL dialect.

| Directory | References |
| --- | --- |
| `easy/` | Filtering/sorting, aggregation, nulls/ratios |
| `mid/` | Joins, subqueries/EXISTS, conditional aggregation |
| `hard/` | Window functions, CTEs/grain, set operations, repair checklist |

Direct `.md` files contain `name` and `description` frontmatter for discovery and matching. Existing nested `SKILL.md` files still work. `mid` maps to the classifier's `medium` level; legacy `medium/` directories remain supported.

Generation selects relevant skills up to the classified difficulty. An explicit SQL knowledge gap loads relevant references alongside `basic/basic.md`. Recoverable execution failures add error-matched references and the repair checklist to the original selected skills. The agent receives file contents through prompts; it does not have unrestricted filesystem access.

References never replace missing schema, data, or user requirements. Approval, read-only validation, model-family isolation, and the three-repair limit still apply. SQL-specific reference files are excluded from Pandas skill selection.
