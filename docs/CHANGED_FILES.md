# Changed files

Changes from the starting commit `e554094`, grouped by component. Local instructions and pre-existing audit scripts are excluded.

## Packaging and documentation

- `.gitignore`
- `README.md`
- `docs/CHANGED_FILES.md`
- `docs/IMPLEMENTATION_AUDIT.md`
- `pyproject.toml`
- `uv.lock`

## Skill content

- `skills/easy/aggregation/SKILL.md`

## agents

- `src/datapilot/agents/documentation_agent.py`
- `src/datapilot/agents/pandas_agent.py`
- `src/datapilot/agents/pandas_operation_compiler.py`
- `src/datapilot/agents/sql_agent.py`
- `src/datapilot/agents/sql_repair_agent.py`
- `src/datapilot/agents/visualization_agent.py`

## Application service

- `src/datapilot/application.py`

## connections

- `src/datapilot/connections/connection_manager.py`

## execution

- `src/datapilot/execution/execution_logger.py`
- `src/datapilot/execution/pandas_executor.py`
- `src/datapilot/execution/sql_executor.py`

## graph

- `src/datapilot/graph/agent_workflow.py`
- `src/datapilot/graph/nodes.py`
- `src/datapilot/graph/pandas_workflow.py`
- `src/datapilot/graph/state.py`

## ingestion

- `src/datapilot/ingestion/file_loader.py`

## knowledge

- `src/datapilot/knowledge/file_knowledge_cache.py`
- `src/datapilot/knowledge/file_knowledge_writer.py`
- `src/datapilot/knowledge/schema_writer.py`

## memory

- `src/datapilot/memory/context_monitor.py`

## models

- `src/datapilot/models/model_manager.py`
- `src/datapilot/models/response_schemas.py`

## persistence

- `src/datapilot/persistence/result_repository.py`
- `src/datapilot/persistence/session_repository.py`
- `src/datapilot/persistence/sqlite_manager.py`

## reports

- `src/datapilot/reports/pdf_report.py`

## skills_engine

- `src/datapilot/skills_engine/basic_knowledge_fallback.py`
- `src/datapilot/skills_engine/complexity_classifier.py`
- `src/datapilot/skills_engine/skill_learning_manager.py`
- `src/datapilot/skills_engine/skill_matcher.py`
- `src/datapilot/skills_engine/skill_orchestrator.py`
- `src/datapilot/skills_engine/skill_registry.py`

## tools

- `src/datapilot/tools/documentation_retriever.py`
- `src/datapilot/tools/search_orchestrator.py`

## ui

- `src/datapilot/ui/analytics_workspace.py`
- `src/datapilot/ui/chart_presenter.py`
- `src/datapilot/ui/connection_form.py`
- `src/datapilot/ui/model_selector.py`
- `src/datapilot/ui/sidebar.py`

## validation

- `src/datapilot/validation/approval_manager.py`
- `src/datapilot/validation/result_verifier.py`
- `src/datapilot/validation/sql_validator.py`

## visualization

- `src/datapilot/visualization/chart_artifacts.py`
- `src/datapilot/visualization/chart_renderer.py`

## Streamlit entry point

- `streamlit_app.py`

## Tests

- `tests/conftest.py`
- `tests/test_application.py`
- `tests/test_components.py`
- `tests/test_distribution.py`
- `tests/test_documentation.py`
- `tests/test_external_integrations.py`
- `tests/test_imports.py`
- `tests/test_launch.py`
- `tests/test_model_limits.py`
- `tests/test_sql_security.py`
- `tests/test_streamlit.py`
- `tests/test_workflows.py`
