# DataPilot

DataPilot is a local Streamlit analytics workbench for SQL databases and CSV/XLSX files. It uses an explicitly selected Ollama or cloud model to generate analytical requests, validates them, and executes them through controlled SQL or Pandas operations.

## Install and launch

Use Python 3.13 or newer and [uv](https://docs.astral.sh/uv/). From the repository root in PowerShell:

```powershell
uv sync --locked
.\.venv\Scripts\Activate.ps1
python app.py
```

Without activating the environment:

```powershell
uv run --locked python app.py
```

For a local headless server:

```powershell
uv run --locked python app.py --server.headless=true --server.address=127.0.0.1
```

Create an analytics session, load a file or connect to a database, configure and save a model, and ask a question. Review the first generated query or file operation plan and approve or reject it. Approval covers subsequent validated read-only analyses of the same source in that session. A rejected request remains rejected.

## Models and credentials

Ollama model discovery uses the configured endpoint, initially `http://localhost:11434`. Select an installed model capable of the configured context window; DataPilot requires at least 35,000 tokens and checks the model's advertised maximum. Supported models expose a reasoning toggle. Local request timeouts default to 180 seconds and can be set from 1 to 600 seconds to accommodate loading and generation. The UI does not download models or start Ollama. Thinking-mode requests follow the [Ollama chat API](https://docs.ollama.com/api/chat).

The audited local configuration is `qwen3.5:4b`, a 35,000-token context, reasoning disabled, and a 180-second request timeout. SQL, CSV, and XLSX analytical workflows were verified with that real model. Structured local requests use JSON schemas in addition to downstream validation. Other installed models can still fail to complete the required structured responses within the bounded output budgets.

Cloud model identifiers must be entered explicitly. Put credentials in the process environment or a local `.env` file:

| Provider | Credential variable |
| --- | --- |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Qwen | `DASHSCOPE_API_KEY` |
| Custom OpenAI-compatible HTTPS endpoint | `CUSTOM_LLM_API_KEY` |

Local documentation retrieval requires `TAVILY_API_KEY` when the model requests documentation. Cloud documentation retrieval uses the selected provider's native search when supported and confirmed. Unsupported, failed, or unconfirmed searches are reported as unavailable; DataPilot never silently switches providers. Retrieved sources must use official documentation domains, and redirects are validated before following them.

Cloud requests can transmit source schema, file profiles, questions, selected skills, and compacted analytical history to the selected provider. Database passwords stay in the active Streamlit session and are not saved in application configuration or checkpoints. Reconnect after restarting the application to resume SQL analysis. Saved analytical artifacts can be viewed without reconnecting.

## Execution and persistence

- SQLite execution opens an existing database in read-only mode with query-only enforcement and a deadline. PostgreSQL and MySQL use read-only transactions; use a dedicated read-only database account too.
- SQL validation rejects multiple statements, writes, unverified functions, file access, extension loading, and schema-qualified function calls. Valid analytical SQL using unsupported functions may be rejected conservatively.
- SQL repairs are limited to three, and every repaired statement is revalidated before execution. Permission, timeout, and connection failures do not trigger speculative repair.
- File analysis compiles validated descriptions to allowlisted filter, select, groupby, sort, and limit operations. It never executes model-generated Python.
- `storage/app.db` stores session configuration, approval decisions, result references, analysis descriptions, and conversation memory. `storage/checkpoints.db` stores LangGraph checkpoints. Pending approvals survive restart without regenerating the plan.
- `sessions/<session_id>/` contains uploaded sources, checksummed result files, and chart artifacts. `storage/reports/<session_id>/` contains on-demand PDF reports. `storage/logs/<session_id>/` contains successful SQL execution logs.
- Results, charts, reports, approvals, and memory are scoped to a session. Changed file contents receive a different source identity and require fresh approval.
- Context monitoring uses a conservative UTF-8 byte estimate as a token upper bound, compacts older history in bounded batches, and restores summaries with recent turns and result references. Requests exceeding the conservative budget fail explicitly.
- Common skills are discovered under `skills/easy`, `skills/mid`, `skills/hard`, and `skills/dialects`; legacy `skills/medium` remains supported. Direct Markdown files and nested `SKILL.md` files are discoverable. Only the selected family's `<family>_skills` directory is loaded. See the [SQL reference catalog](skills/README.md). Explicit SQL knowledge gaps load relevant references alongside `skills/basic/basic.md`; repair retries receive diagnostic references and the original selected skills.

Matplotlib and Seaborn charts are saved as PNG files. Plotly and Bokeh charts are saved as interactive HTML downloads. PDF reports include the selected result, its question and executed query/operations, and associated PNG charts. Truncated results are marked in the UI and reports.

`DATAPILOT_HOME` can select a separate application working directory. It must contain the `skills` directory; generated storage, knowledge, and session directories are created there. These local files contain analytical data, so keep them in a location appropriate for that data.

## Verification

```powershell
uv run --locked ruff check src app.py streamlit_app.py tests
uv run --locked pytest -q -rs
uv pip check
uv build
```

Tests exercise real SQLite databases, actual CSV/XLSX files, persistent LangGraph SQLite checkpoints, HTTP model-adapter fixtures, Streamlit interactions, chart serialization, PDF generation, and security regressions. An HTTP fixture is not a real model. Live tests are reported separately and skip with a reason when prerequisites are absent.

Select an installed model for a real Ollama check:

```powershell
$env:DATAPILOT_TEST_OLLAMA_MODEL = 'your-installed-model'
$env:DATAPILOT_TEST_REQUEST_TIMEOUT = '180'
uv run --locked pytest tests/test_external_integrations.py -q -rs
```

For live cloud tests, supply the provider credential and the corresponding explicit model variable: `DATAPILOT_TEST_OPENAI_MODEL`, `DATAPILOT_TEST_ANTHROPIC_MODEL`, `DATAPILOT_TEST_DEEPSEEK_MODEL`, or `DATAPILOT_TEST_QWEN_MODEL`. For external database checks use `DATAPILOT_TEST_POSTGRES_URL` with a `postgresql+psycopg://` URL or `DATAPILOT_TEST_MYSQL_URL` with a `mysql+pymysql://` URL. These checks execute only `SELECT 1` against the external database and are not a substitute for a deployment-specific analytical workflow test.

See [the implementation audit](docs/IMPLEMENTATION_AUDIT.md) for tested scope and release limitations.
