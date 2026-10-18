from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from datapilot.agents.visualization_agent import VisualizationPlan
from datapilot.persistence.analysis_evidence import load_evidence
from datapilot.persistence.dashboard_repository import (
    advance_refresh,
    cancel_refresh,
    filter_frame,
    kpi_value,
    list_cards,
    load_filters,
    move_card,
    pin_card,
    remove_card,
    result_frame,
    save_filters,
    start_refresh,
)
from datapilot.ui.chart_presenter import present_chart
from datapilot.visualization.chart_renderer import render_chart


def render_pin_controls(root: Path, session_id: str, result_id: str, frame: pd.DataFrame) -> None:
    with st.expander("Pin KPI to dashboard"):
        title = st.text_input(
            "KPI title", value="Sales total", max_chars=100, key=f"kpi_title_{result_id}"
        )
        aggregation = st.selectbox(
            "KPI calculation",
            ["sum", "mean", "min", "max", "count"],
            key=f"kpi_aggregation_{result_id}",
        )
        numeric = list(frame.select_dtypes(include="number").columns)
        column = (
            st.selectbox("KPI column", numeric, key=f"kpi_column_{result_id}") if numeric else None
        )
        st.caption("Calculations use the saved result rows. Count counts result rows.")
        if st.button("Pin KPI", key=f"pin_kpi_{result_id}"):
            pin_card(
                root,
                session_id,
                result_id,
                {"kind": "kpi", "title": title, "aggregation": aggregation, "column": column},
            )
            st.rerun()


def pin_chart(root: Path, session_id: str, result_id: str, plan: VisualizationPlan) -> None:
    pin_card(
        root, session_id, result_id, {"kind": "chart", "title": plan.title, "plan": asdict(plan)}
    )


def render_dashboard(root: Path, session_id: str, application: Any | None) -> None:
    database = root / "storage" / "app.db"
    cards = list_cards(database, session_id)
    if not cards:
        return
    with st.expander("Dashboard", expanded=True):
        st.caption(
            "Cards use saved results. Shared filters apply to those results, after aggregation."
        )
        st.caption(
            "Refresh reruns pinned questions against the currently configured source and model."
        )
        try:
            if st.button("Cancel dashboard refresh", key=f"cancel_refresh_{session_id}"):
                cancel_refresh(database, session_id)
                st.rerun()
            if st.button(
                "Refresh dashboard analyses",
                key=f"refresh_dashboard_{session_id}",
                disabled=application is None,
            ):
                if application.snapshot()["interrupts"]:
                    st.warning("Approve or reject the pending analysis first.")
                else:
                    start_refresh(database, session_id)
                    with st.spinner("Refreshing dashboard analyses"):
                        advance_refresh(application)
                    st.rerun()
            frames = {
                card["result_id"]: result_frame(root, session_id, card["result_id"])
                for card in cards
            }
            common = sorted(set.intersection(*(set(frame.columns) for frame in frames.values())))
            filters = load_filters(database, session_id)
            if st.button("Clear shared filters", key=f"clear_filters_{session_id}"):
                save_filters(database, session_id, [])
                st.rerun()
            with st.expander("Shared filters"):
                column = st.selectbox("Filter column", common, key=f"dashboard_column_{session_id}")
                if column:
                    options = sorted(
                        {
                            str(value)
                            for frame in frames.values()
                            for value in frame[column].dropna()
                        }
                    )
                    if len(options) > 1000:
                        st.info("Choose a column with at most 1,000 distinct values.")
                    else:
                        values = st.multiselect(
                            "Include values", options, key=f"dashboard_values_{session_id}_{column}"
                        )
                        missing = st.checkbox(
                            "Include missing values", key=f"dashboard_missing_{session_id}_{column}"
                        )
                        if st.button("Apply shared filter", key=f"apply_filter_{session_id}"):
                            updated = [item for item in filters if item["column"] != column]
                            updated.append(
                                {"column": column, "values": values, "include_missing": missing}
                            )
                            save_filters(database, session_id, updated)
                            st.rerun()
                if filters:
                    st.json(filters)
            layout = st.columns(2)
            for index, card in enumerate(cards):
                with layout[index % 2], st.container(border=True):
                    try:
                        definition = card["definition"]
                        frame = filter_frame(frames[card["result_id"]], filters)
                        if definition["kind"] == "kpi":
                            value = kpi_value(frame, definition)
                            st.metric(
                                definition["title"], "No data" if value is None else f"{value:,.2f}"
                            )
                        elif frame.empty:
                            st.info(f"{definition['title']}: no rows match the filters.")
                        else:
                            plan = VisualizationPlan(**definition["plan"])
                            if plan.library == "bokeh":
                                plan = VisualizationPlan(**{**asdict(plan), "library": "plotly"})
                            chart = render_chart(frame, plan)
                            present_chart(chart, key=f"dashboard_chart_{card['card_id']}")
                            if chart.library in {"matplotlib", "seaborn"}:
                                chart.figure.clear()
                        evidence = load_evidence(database, session_id, card["result_id"])
                        if evidence:
                            st.caption(
                                f"Updated {evidence['created_at']} · {evidence['row_count']} saved rows"
                            )
                            if evidence["truncated"]:
                                st.warning(
                                    "This card uses a truncated result; its values may be incomplete."
                                )
                    except (ValueError, TypeError, KeyError) as error:
                        st.error(f"Could not render card: {error}")
                    if st.button("Move up", key=f"up_{card['card_id']}", disabled=index == 0):
                        move_card(database, session_id, card["card_id"], -1)
                        st.rerun()
                    if st.button("Remove card", key=f"remove_{card['card_id']}"):
                        remove_card(database, session_id, card["card_id"])
                        st.rerun()
        except (ValueError, TypeError, KeyError, LookupError, OSError, RuntimeError) as error:
            st.error(f"Could not load dashboard: {error}")
