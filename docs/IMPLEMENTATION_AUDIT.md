# DataPilot implementation and release audit

Audit date: October 17, 2026. Work was performed exclusively on `codex`.

## Initial findings and implementation order

The initial working tree contained changes to `pyproject.toml` and `uv.lock`, an untracked chart renderer, local audit scripts, and local instructions. Existing component work was retained and integrated. The audit scripts and `AGENTS.md` remain local and are excluded from commits.

| Priority | Verified initial issue | Implemented outcome |
| --- | --- | --- |
| 1 | Most backend dependencies were undeclared, package build metadata was absent, and no persistent test suite existed | Explicit runtime/dev dependencies, editable installation, locked resolution, wheel/source builds, driver import checks, and regression tests |
| 2 | Strict SQL parsing used an incompatible error-level argument; unsafe/unverified functions were insufficiently restricted | Strict AST parsing, conservative function validation, query-only SQLite execution, literal-safe driver execution, and real SQLite security tests |
| 3 | SQL and Pandas approval branches ended rather than pausing durably | LangGraph interrupts preserve generated plans; decisions resume checkpoints without regenerating them |
| 4 | Basic knowledge fallback and skills were disconnected from the application | SQL fallback is used by generation; common/model-specific skill selection is connected to SQL and file analysis |
| 5 | Persistence initialization and full application orchestration were disconnected | Application service initializes all stores, binds source identities, saves result references, logs SQL execution, and restores checkpoints |
| 6 | Memory primitives had no application history integration | Per-session/source memory, bounded summarization batches, compaction, reconstruction, and recovery from the latest successful checkpoint |
| 7 | Missing documentation credentials caused retrieval to abort; redirect validation happened after following redirects | Explicit unavailable status, pre-request redirect checks, official-domain checks for cloud citations, and no provider substitution |
| 8 | Charts/reports/results were disconnected; desktop plotting could fail in Windows; PDF viewer and PostgreSQL native dependencies were absent | Headless figures, checksummed result restoration, persisted chart artifacts, result-linked PDF generation, PDF preview, and binary PostgreSQL driver |
| 9 | Existing mock claims had no reproducible integration suite | Persistent unit, security, SQLite/file/checkpoint, HTTP-contract, Streamlit, packaging, and opt-in live integration tests |
| 10 | Streamlit configured sources but had no analytical execution flow | Model selection, questions, approval/rejection, saved results, downloads, charts, reports, and restoration |
| 11 | No release audit or reproducible launch verification | Real `python app.py` health check with process cleanup, isolated wheel import verification, this audit, and installation instructions |

The distribution audit caught a root ignore rule that also matched the backend `knowledge` package. That rule is now anchored to the repository root. The distribution regression test builds a wheel and source archive, verifies all backend Python modules are included, rejects packaged `AGENTS.md` files, and imports the extracted wheel in a separate interpreter.

## Verification evidence

The final regression suite contains real SQLite query execution and repair, CSV and XLSX loading/aggregation, close-and-reopen SQLite checkpoint recovery, source-change approval checks, persistent memory reconstruction, actual filesystem model-family isolation checks, chart generation with four libraries, PDF text/data checks, Streamlit interaction tests, distribution imports, and a real application server health check.

The final combined regression run explicitly selects `qwen3.5:4b` with a 180-second timeout and reports **121 passed, 6 skipped**. The skipped checks require cloud credentials/model identifiers or external database URLs. Ruff passes over `src`, `app.py`, `streamlit_app.py`, and `tests`. `uv pip check` reports compatible installed packages. The lockfile check and wheel/source builds pass.

Model-generated content in offline end-to-end tests comes from controlled HTTP or function fixtures. This proves integration contracts and actual downstream execution, not the capabilities or correctness of a real model.

Separate real Ollama tests were attempted with the installed models:

| Model | Actual result |
| --- | --- |
| `qwen3.5:4b` | Initial 60-second timeouts and structured-response failures exposed integration issues. After configurable timeouts and schema-constrained output were implemented, actual SQL, CSV, and XLSX workflows passed with independently expected totals |
| `deepseek-r1:1.5b` | Initial 60-second timeout; connectivity/inference smoke test passed with a 180-second timeout. The analytical workflows failed because structured decisions were malformed or incomplete within bounded output budgets; this model is not established as analytically compatible |

Ollama model discovery and `/api/show` metadata requests succeeded. The Qwen model advertises a 262,144-token maximum and supports disabling reasoning; the application checks the advertised context maximum and exposes reasoning selection only when supported. Early local logs showed a runner loading in approximately 24 seconds and a request cancelled at one minute. Local timeouts are now configurable, with a 180-second default for new UI configurations. The final tested configuration uses a 35,000-token context and reasoning disabled. No earlier failure is counted as a success.

The live tests also exposed invalid SQL response field types and reversed Pandas aggregation mappings that fixture tests had not revealed. Structured local responses now have explicit schemas. The Pandas compiler schema restricts operation kinds, exact parameter structures, verified columns, aggregation names, and operation counts. The ordinary validators still revalidate responses before execution. These fixes were retested with the real Qwen model.

No cloud model credentials, Tavily key, or PostgreSQL/MySQL test URLs were configured during the audit. Real cloud inference, native cloud search, Tavily documentation retrieval, and external database analytical workflows remain unverified. PostgreSQL and MySQL driver imports pass, and PostgreSQL/MySQL read-only transaction setup is implemented; its live behavior has not been established here.

## Release assessment

**Local release candidate: SQL, CSV, and XLSX workflows are verified with a real supported model, and offline application/security checks pass. Cloud and external database release readiness remain unverified.** This is not a claim that every provider, installed model, or deployment configuration is release-ready.

The remaining external work is to configure explicit cloud test models and credentials, validate PostgreSQL/MySQL deployment behavior using read-only accounts, and configure `TAVILY_API_KEY` and/or a supported selected cloud provider to validate real documentation retrieval. No unresolved critical local blocker was observed in the tested Qwen configuration.

Use the commands in the README. To reproduce the successful tested local configuration:

```powershell
$env:DATAPILOT_TEST_OLLAMA_MODEL = 'qwen3.5:4b'
$env:DATAPILOT_TEST_REQUEST_TIMEOUT = '180'
uv run --locked pytest tests/test_external_integrations.py::test_real_ollama -q -rs
```

Run all three real analytical source workflows:

```powershell
uv run --locked pytest tests/test_external_integrations.py::test_real_model_analytics -q -rs
```

Provider selection stays explicit. No cloud account, runtime configuration, model installation, or database permissions were changed to work around missing prerequisites.

## Operational limits

- SQL repair is bounded to three repairs; execution results default to 1,000 rows. File execution defaults to 1,000,000 input rows and 10,000 result rows.
- The current file operation vocabulary is filter/select/groupby/sort/limit with allowlisted aggregations. Arbitrary Pandas code and advanced operations outside that vocabulary are rejected.
- Model context accounting deliberately uses a conservative UTF-8 estimate. Large schemas/skills may be rejected earlier than a model's exact tokenizer would require.
- PDF previews support at most 10 columns, default to 100 rows, and embed at most 12 associated PNG/JPEG charts. Interactive HTML charts are downloadable and are not embedded into PDFs. The default report fonts do not establish full multilingual typography support.
- SQL credentials are intentionally not restored from disk. Reconnect to resume execution after restarting; saved results/reports remain accessible.
- Automated promotion of model-generated skills is not enabled. The existing verification/save API requires independently supplied expected results before writing a model-specific skill.
- The application is a local workbench. Multi-user authentication, remote deployment isolation, and a full dependency vulnerability audit are outside the tested release scope.

## Changed components

The complete [changed-file manifest](CHANGED_FILES.md) lists paths grouped by component.

- Packaging: `.gitignore`, `pyproject.toml`, `uv.lock`, and built-distribution tests.
- SQL/Pandas: SQL validation/execution, approval-backed workflows, retry tests, orchestration state, and shared source/result handling.
- Application/memory: `src/datapilot/application.py`, workflow context propagation, SQLite connection safeguards, and persisted history/recovery tests.
- Skills/documentation/models: basic fallback wiring, common aggregation skill, model-family isolation, bounded model requests, Ollama capability inspection, and documentation redirect/source checks.
- Artifacts/UI: result repository, chart renderer/artifacts/presenters, connection/model/sidebar controls, `analytics_workspace.py`, and `streamlit_app.py`.
- Quality/documentation: `tests/`, this audit, and `README.md`. Import ordering and compatibility fixes were applied to existing modules to satisfy Ruff.

Only `origin/codex` is the push destination. No pull request or branch merge was created. Local `AGENTS.md` and existing audit scripts are left untouched.

Implementation commits on `codex`:

- `57d0f1e` — `fix(core): package dependencies and resume approved analytics safely`
- `fe8f0ad` — `feat(app): integrate persistent analytics and verified Streamlit workflows`

The audit and changed-file manifest are delivered in a separate documentation commit.
