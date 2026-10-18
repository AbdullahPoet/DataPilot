# Workbench feature delivery

Implemented on `develop` on October 18, 2026. The user explicitly selected this branch instead of the earlier `codex` branch policy. No pull request or merge is part of this delivery.

## Components

- Ingestion: `ingestion/joined_source.py` loads mixed CSV/XLSX sources, checks explicit key relationships, estimates output size before merging, reports unmatched/duplicate keys, and produces a versioned joined profile. Joins are configured by the user, not generated as arbitrary code.
- Evidence: `persistence/analysis_evidence.py`, workflow state, and `application.py` record immutable per-result provenance, the executed calculation, planning assumptions/explanation, row count, model, attempts, and truncation. SQL source identity includes the refreshed schema fingerprint. Model-reported assumptions trigger explicit review.
- Learning: `skills_engine/query_learning.py` stores distinct execution examples and replay receipts. Two matching executions enable exact-question retrieval; feedback can exclude a plan. Scope includes the session, source/profile, model/provider, and endpoint. Forgetting examples preserves receipts so old checkpoints cannot repopulate them. No weights or verified skill files are updated.
- Dashboards: `persistence/dashboard_repository.py` persists cards, filters, ordering, and refresh queues. Refresh deduplicates questions and reuses normal approval-backed workflows. Cards update only after a new result passes compatibility checks; queues survive pending approval and restart.
- Streamlit: `ui/join_workspace.py`, `ui/dashboard_workspace.py`, and the analytics workspace expose joins, evidence, feedback, learning controls, KPI/chart pinning, shared filters, refresh, and removal. Chart artifacts retain their visualization plan for dashboard reuse. Existing chart downloads and PDF exports remain available.

## Validation

Final regression: **156 passed, 15 skipped in 45.72 seconds**. Ruff and `git diff --check` pass. `uv pip check` verifies 97 compatible installed packages, and `uv lock --check --offline` passes. The regression includes wheel/source builds, imports of all packaged backend modules, SQL security tests, chart/PDF generation, and a real `python app.py` server health check. An initial packaging check failed because `uv` was absent from the shell PATH; using the existing `C:\Users\Abdullah\.local\bin\uv.exe` installation resolved it without dependency changes.

Tests cover real Pandas joins and aggregations, mixed CSV/XLSX loading, SQLite execution, changed-source approval, assumption review, persisted evidence, model/session/source isolation, negative feedback, disabled learning, forget/replay behavior, dashboard filtering and ordering, chart pinning, refresh deduplication, restart recovery, rejected refresh, and Streamlit interactions.

Model responses in offline integration tests are fixtures. They establish downstream behavior, not live model quality. The local Ollama endpoint refused connections during this delivery; no new real-model success is claimed. Cloud inference, native provider search, Tavily, and PostgreSQL/MySQL checks require their configured services and opt-in environment variables.

Run with Python 3.13+ and the locked environment:

```powershell
uv sync --locked
uv run --locked ruff check src app.py streamlit_app.py tests
uv run --locked pytest -q -rs
uv pip check
uv lock --check
uv run --locked python app.py
```

Feature boundaries: two to eight files; left/inner joins with one key per pair; at most 1,000,000 rows per input/intermediate join; up to 24 cards per session; shared filters operate on saved result rows after aggregation. SQL evidence fingerprints schemas rather than live database contents. Ambiguity review depends on model-reported assumptions and user clarification. Existing older results/charts may lack evidence or a saved chart plan and must be regenerated to use those features.
