from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from datapilot.agents.visualization_agent import VisualizationPlan


class ChartRenderingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RenderedChart:
    library: str
    chart_type: str
    figure: Any
    row_count: int


def _validate_data(frame: pd.DataFrame, plan: VisualizationPlan, max_rows: int) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise ChartRenderingError("A Pandas DataFrame is required")
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or max_rows < 1:
        raise ChartRenderingError("max_rows must be a positive integer")
    if frame.empty:
        raise ChartRenderingError("Cannot render an empty dataset")
    if frame.columns.has_duplicates:
        raise ChartRenderingError("Dataset has duplicate column names")
    required = [plan.x] + ([plan.y] if plan.y is not None else [])
    if any(column not in frame.columns for column in required):
        raise ChartRenderingError("Chart references a missing column")
    data = frame.loc[:, required].head(max_rows).copy()
    if plan.chart_type in {"bar", "line", "scatter", "pie"} and plan.y is None:
        raise ChartRenderingError("Chart requires a Y column")
    if plan.chart_type in {"histogram", "box"} and plan.y is not None:
        raise ChartRenderingError("Chart supports only an X column")
    if plan.chart_type in {"scatter", "histogram", "box"} and not pd.api.types.is_numeric_dtype(data[plan.x]):
        raise ChartRenderingError("X column must be numeric")
    if plan.y is not None and not pd.api.types.is_numeric_dtype(data[plan.y]):
        raise ChartRenderingError("Y column must be numeric")
    data = data.dropna(subset=required)
    if data.empty:
        raise ChartRenderingError("Chart has no non-null observations")
    if plan.chart_type == "pie" and ((data[plan.y] < 0).any() or data[plan.y].sum() <= 0):
        raise ChartRenderingError("Pie chart values must be nonnegative with a positive total")
    return data


def _render_matplotlib(data: pd.DataFrame, plan: VisualizationPlan, seaborn_mode: bool) -> Any:
    from matplotlib.figure import Figure

    figure = Figure()
    axes = figure.subplots()
    try:
        chart = plan.chart_type
        x, y = plan.x, plan.y
        if seaborn_mode and chart != "pie":
            import seaborn as sns

            if chart == "bar":
                aggregated = data.groupby(x, sort=False, dropna=False)[y].sum()
                axes.bar(aggregated.index.astype(str), aggregated.to_numpy())
            elif chart == "line":
                sns.lineplot(data=data, x=x, y=y, estimator=None, ax=axes)
            elif chart == "scatter":
                sns.scatterplot(data=data, x=x, y=y, ax=axes)
            elif chart == "histogram":
                axes.hist(data[x])
            elif chart == "box":
                axes.boxplot(data[x])
        elif chart == "bar":
            aggregated = data.groupby(x, sort=False, dropna=False)[y].sum()
            axes.bar(aggregated.index.astype(str), aggregated.to_numpy())
        elif chart == "line":
            axes.plot(data[x], data[y])
        elif chart == "scatter":
            axes.scatter(data[x], data[y])
        elif chart == "histogram":
            axes.hist(data[x])
        elif chart == "box":
            axes.boxplot(data[x])
        elif chart == "pie":
            aggregated = data.groupby(x, sort=False, dropna=False)[y].sum()
            axes.pie(aggregated.to_numpy(), labels=aggregated.index.astype(str))
        else:
            raise ChartRenderingError("Unsupported chart type")
        axes.set_title(plan.title)
        if chart != "pie":
            axes.set_xlabel(plan.x_label)
            axes.set_ylabel(plan.y_label)
        figure.tight_layout()
        return figure
    except Exception:
        figure.clear()
        raise


def _render_plotly(data: pd.DataFrame, plan: VisualizationPlan) -> Any:
    import plotly.express as px

    x, y = plan.x, plan.y
    common = {"title": plan.title, "labels": {x: plan.x_label, **({y: plan.y_label} if y else {})}}
    if plan.chart_type == "bar":
        grouped = data.groupby(x, sort=False, as_index=False)[y].sum()
        return px.bar(grouped, x=x, y=y, **common)
    if plan.chart_type == "line":
        return px.line(data, x=x, y=y, **common)
    if plan.chart_type == "scatter":
        return px.scatter(data, x=x, y=y, **common)
    if plan.chart_type == "histogram":
        return px.histogram(data, x=x, **common)
    if plan.chart_type == "box":
        return px.box(data, y=x, title=plan.title, labels={x: plan.x_label})
    if plan.chart_type == "pie":
        grouped = data.groupby(x, sort=False, as_index=False)[y].sum()
        return px.pie(grouped, names=x, values=y, title=plan.title)
    raise ChartRenderingError("Unsupported chart type")


def _render_bokeh(data: pd.DataFrame, plan: VisualizationPlan) -> Any:
    from bokeh.models import ColumnDataSource
    from bokeh.plotting import figure

    x, y = plan.x, plan.y
    chart = plan.chart_type
    if chart in {"bar", "pie"}:
        grouped = data.groupby(x, sort=False)[y].sum()
        labels = grouped.index.astype(str).tolist()
        values = grouped.to_numpy(dtype=float)
        if chart == "bar":
            plot = figure(title=plan.title, x_range=labels)
            plot.vbar(x=labels, top=values, width=0.8)
        else:
            from math import pi

            from bokeh.palettes import Category20, Turbo256

            count = len(values)
            palette = Category20[20] if count <= 20 else Turbo256
            colors = [palette[index * len(palette) // count] for index in range(count)]
            angles = np.cumsum(np.concatenate(([0.0], values / values.sum() * 2 * pi)))
            source = ColumnDataSource({"start": angles[:-1], "end": angles[1:], "color": colors, "label": labels})
            plot = figure(title=plan.title, x_range=(-1.2, 1.2), y_range=(-1.2, 1.2))
            plot.wedge(x=0, y=0, radius=1, start_angle="start", end_angle="end", color="color", legend_field="label", source=source)
    else:
        plot = figure(title=plan.title)
        if chart == "line":
            plot.line(data[x].tolist(), data[y].tolist())
        elif chart == "scatter":
            plot.scatter(data[x].tolist(), data[y].tolist())
        elif chart == "histogram":
            frequencies, edges = np.histogram(data[x].to_numpy(dtype=float), bins="auto")
            plot.quad(top=frequencies, bottom=0, left=edges[:-1], right=edges[1:])
        elif chart == "box":
            values = data[x].to_numpy(dtype=float)
            q1, median, q3 = np.percentile(values, [25, 50, 75])
            lower = max(values.min(), q1 - 1.5 * (q3 - q1))
            upper = min(values.max(), q3 + 1.5 * (q3 - q1))
            plot.segment([0], [lower], [0], [upper])
            plot.vbar([0], 0.5, [q3], [q1])
            plot.segment([-0.25], [median], [0.25], [median])
            plot.segment([-0.12, -0.12], [lower, upper], [0.12, 0.12], [lower, upper])
        else:
            raise ChartRenderingError("Unsupported chart type")
    plot.xaxis.axis_label = plan.x_label
    plot.yaxis.axis_label = plan.y_label
    return plot


def render_chart(frame: pd.DataFrame, plan: VisualizationPlan, *, max_rows: int = 10000) -> RenderedChart:
    if not isinstance(plan, VisualizationPlan):
        raise ChartRenderingError("A validated VisualizationPlan is required")
    if plan.library not in {"matplotlib", "seaborn", "plotly", "bokeh"}:
        raise ChartRenderingError("Unsupported visualization library")
    data = _validate_data(frame, plan, max_rows)
    try:
        if plan.library in {"matplotlib", "seaborn"}:
            chart = _render_matplotlib(data, plan, plan.library == "seaborn")
        elif plan.library == "plotly":
            chart = _render_plotly(data, plan)
        else:
            chart = _render_bokeh(data, plan)
    except ChartRenderingError:
        raise
    except (ValueError, TypeError, ImportError, RuntimeError) as error:
        raise ChartRenderingError(f"Unable to render {plan.chart_type} using {plan.library}: {error}") from error
    return RenderedChart(library=plan.library, chart_type=plan.chart_type, figure=chart, row_count=len(data))
