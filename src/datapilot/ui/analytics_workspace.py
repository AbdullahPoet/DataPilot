import json
from pathlib import Path

import pandas as pd
import streamlit as st

from datapilot.agents.visualization_agent import VisualizationPlan, plan_visualization
from datapilot.application import AnalyticsApplication
from datapilot.persistence.result_repository import list_results, load_result
from datapilot.persistence.sqlite_manager import open_database
from datapilot.reports.pdf_report import ReportData, generate_pdf_report
from datapilot.ui.chart_presenter import present_saved_chart
from datapilot.ui.model_selector import render_model_selector
from datapilot.ui.report_presenter import list_saved_reports, present_saved_report
from datapilot.visualization.chart_artifacts import ChartArtifact, save_chart_artifact
from datapilot.visualization.chart_renderer import render_chart


def render_analytics(root: Path, session_id: str, configuration: dict[str, object]) -> None:
    model = configuration.get("model_configuration")
    if isinstance(model, dict):
        st.caption(f"Selected model: {model['provider']} / {model['model']}")
    if st.checkbox(
        "Configure model", value=not isinstance(model, dict), key=f"model_config_{session_id}"
    ):
        selected = render_model_selector()
        if selected and st.button("Save model", key=f"save_model_{session_id}"):
            updated = {**configuration, "model_configuration": selected, "model_configured": True}
            with open_database(root / "storage" / "app.db") as connection:
                connection.execute(
                    "UPDATE sessions SET configuration_json = ? WHERE session_id = ?",
                    (json.dumps(updated), session_id),
                )
            st.session_state.session_config = updated
            st.rerun()
    if isinstance(model, dict) and configuration.get("source_configured"):
        try:
            application = AnalyticsApplication(
                root,
                session_id,
                model,
                connection_url=st.session_state.get(f"connection_{session_id}"),
            )
            snapshot = application.snapshot()
            if snapshot["interrupts"]:
                st.subheader("Review first execution")
                st.write(
                    "Approval allows subsequent validated read-only analyses for this source in this session."
                )
                st.code(
                    snapshot["values"].get("generated_query")
                    or json.dumps(snapshot["values"].get("pandas_operations"), indent=2)
                )
                approve, reject = st.columns(2)
                decision = None
                if approve.button("Approve execution", key=f"approve_{session_id}"):
                    decision = True
                if reject.button("Reject execution", key=f"reject_{session_id}"):
                    decision = False
                if decision is not None:
                    application.run(decision=decision)
                    st.rerun()
            else:
                question = st.chat_input(
                    "Ask a question about this data", key=f"question_{session_id}"
                )
                if question:
                    with st.spinner("Preparing analysis"):
                        application.run(question)
                    st.rerun()
                values = snapshot["values"]
                if values.get("approval_status") == "rejected":
                    st.info("Execution was rejected. Ask a new question to continue.")
                if values.get("documentation_status") == "unavailable":
                    st.warning(
                        "Requested documentation was unavailable for this provider. No alternative provider was used."
                    )
        except (
            ValueError,
            TypeError,
            LookupError,
            OSError,
            RuntimeError,
            PermissionError,
        ) as error:
            st.error(str(error))
    render_saved_results(root, session_id, model)


def render_saved_results(root: Path, session_id: str, model: dict[str, object] | None) -> None:
    database = root / "storage" / "app.db"
    artifacts = root / "sessions"
    try:
        results = list_results(database, session_id, artifacts)
        if results:
            st.subheader("Saved results")
            selected = st.selectbox(
                "Analysis result",
                results,
                format_func=lambda result: f"{result.created_at} · {result.row_count} rows",
                key=f"result_{session_id}",
            )
            data = load_result(
                database_path=database,
                artifacts_directory=artifacts,
                session_id=session_id,
                result_id=selected.result_id,
            )
            frame = (
                data.dataframe
                if hasattr(data, "dataframe")
                else pd.DataFrame(data.rows, columns=data.columns)
            )
            st.dataframe(frame, width="stretch")
            if data.truncated:
                st.warning(
                    "This result is truncated. Totals computed from displayed rows may be incomplete."
                )
            st.download_button(
                "Download result CSV",
                frame.to_csv(index=False),
                "analysis.csv",
                "text/csv",
                key=f"csv_{selected.result_id}",
            )
            with open_database(database) as connection:
                details = connection.execute(
                    "SELECT question, executed_query FROM analysis_details WHERE result_id = ? AND session_id = ?",
                    (selected.result_id, session_id),
                ).fetchone()
            render_chart_controls(
                root,
                session_id,
                frame,
                model,
                selected.result_id,
                "sql" if selected.kind == "sql" else "csv",
            )
            if st.button("Generate PDF report", key=f"pdf_{selected.result_id}"):
                generate_pdf_report(
                    ReportData(
                        title="DataPilot Analysis",
                        session_id=session_id,
                        question=details["question"] if details else "Saved analytical result",
                        summary=f"Result {selected.result_id}: {data.row_count} returned rows.",
                        columns=tuple(frame.columns),
                        rows=tuple(frame.itertuples(index=False, name=None)),
                        source_id=selected.source_id,
                        truncated=data.truncated,
                        executed_query=details["executed_query"] if details else "",
                        chart_paths=tuple(
                            path.with_suffix(".png")
                            for path in sorted((artifacts / session_id / "charts").glob("*.json"))
                            if path.stat().st_size <= 65536
                            and not path.is_symlink()
                            and json.loads(path.read_text()).get("result_id") == selected.result_id
                            and path.with_suffix(".png").is_file()
                        )[-12:],
                    ),
                    reports_directory=root / "storage" / "reports",
                )
                st.rerun()
        render_saved_charts(root, session_id)
        reports = list_saved_reports(
            reports_directory=root / "storage" / "reports", session_id=session_id
        )
        if reports:
            with st.expander("Saved PDF reports"):
                report = st.selectbox(
                    "Report",
                    reports,
                    format_func=lambda item: item.filename,
                    key=f"reports_{session_id}",
                )
                present_saved_report(report, reports_directory=root / "storage" / "reports")
    except (ValueError, OSError, LookupError, TypeError, RuntimeError, KeyError) as error:
        st.error(f"Could not restore analytical artifacts: {error}")


def render_chart_controls(
    root: Path,
    session_id: str,
    frame: pd.DataFrame,
    model: dict[str, object] | None,
    result_id: str,
    source_type: str,
) -> None:
    if frame.empty or not len(frame.columns):
        return
    with st.expander("Create chart"):
        library = st.selectbox(
            "Chart library",
            ["matplotlib", "seaborn", "plotly", "bokeh"],
            key=f"library_{session_id}",
        )
        chart_type = st.selectbox(
            "Chart type",
            ["bar", "line", "scatter", "histogram", "box", "pie"],
            key=f"chart_type_{session_id}",
        )
        x = st.selectbox("X column", list(frame.columns), key=f"x_{session_id}")
        y = (
            None
            if chart_type in {"histogram", "box"}
            else st.selectbox(
                "Y column",
                list(frame.columns),
                index=min(1, len(frame.columns) - 1),
                key=f"y_{session_id}",
            )
        )
        plan = None
        if st.button("Create chart", key=f"chart_{session_id}"):
            plan = VisualizationPlan(
                chart_type,
                library,
                x,
                y,
                "Analysis",
                x,
                y or "Count",
                "User selected",
                "manual",
                "manual",
            )
        if isinstance(model, dict) and st.button(
            "Suggest chart with selected model", key=f"suggest_{session_id}"
        ):
            plan = plan_visualization(
                "Visualize this analytical result",
                {name: str(dtype) for name, dtype in frame.dtypes.items()},
                model,
                source_type=source_type,
                row_count=len(frame),
            )
        if plan is not None:
            chart = render_chart(frame, plan)
            save_chart_artifact(
                chart,
                artifacts_directory=root / "sessions",
                session_id=session_id,
                title=plan.title,
                result_id=result_id,
            )
            if chart.library in {"matplotlib", "seaborn"}:
                chart.figure.clear()
            st.rerun()


def render_saved_charts(root: Path, session_id: str) -> None:
    directory = root / "sessions" / session_id / "charts"
    metadata_files = sorted(directory.glob("*.json"), reverse=True)
    if not metadata_files:
        return
    with st.expander("Saved charts"):
        selected = st.selectbox(
            "Chart",
            metadata_files,
            format_func=lambda path: path.stem,
            key=f"saved_chart_{session_id}",
        )
        if selected.is_symlink() or selected.stat().st_size > 65536:
            raise ValueError("Unsafe chart metadata")
        metadata = json.loads(selected.read_text(encoding="utf-8"))
        artifact = ChartArtifact(
            session_id,
            metadata["library"],
            metadata["chart_type"],
            directory / metadata["artifact_file"],
            selected,
            metadata["media_type"],
            metadata["row_count"],
            metadata["created_at"],
        )
        present_saved_chart(artifact, artifacts_directory=root / "sessions")
