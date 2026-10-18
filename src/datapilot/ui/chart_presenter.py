import json
from pathlib import Path
from typing import Any

from datapilot.visualization.chart_artifacts import ChartArtifact
from datapilot.visualization.chart_renderer import RenderedChart


class ChartPresentationError(ValueError):
    pass


def _streamlit_client(client: Any | None) -> Any:
    if client is not None:
        return client
    import streamlit as st

    return st


def present_chart(
    chart: RenderedChart, *, client: Any | None = None, key: str | None = None
) -> None:
    if not isinstance(chart, RenderedChart):
        raise ChartPresentationError("A RenderedChart is required")
    if chart.row_count < 1:
        raise ChartPresentationError("Chart contains no observations")
    st = _streamlit_client(client)
    if chart.library in {"matplotlib", "seaborn"}:
        from matplotlib.figure import Figure

        if not isinstance(chart.figure, Figure):
            raise ChartPresentationError("Invalid Matplotlib figure")
        st.pyplot(chart.figure, clear_figure=False)
    elif chart.library == "plotly":
        from plotly.graph_objects import Figure

        if not isinstance(chart.figure, Figure):
            raise ChartPresentationError("Invalid Plotly figure")
        st.plotly_chart(chart.figure, width="stretch", key=key)
    elif chart.library == "bokeh":
        from bokeh.models import Model

        if not isinstance(chart.figure, Model):
            raise ChartPresentationError("Invalid Bokeh model")
        if not callable(getattr(st, "bokeh_chart", None)):
            raise ChartPresentationError(
                "Installed Streamlit version does not support Bokeh charts"
            )
        st.bokeh_chart(chart.figure, use_container_width=True)
    else:
        raise ChartPresentationError("Unsupported chart library")


def present_saved_chart(
    artifact: ChartArtifact,
    *,
    artifacts_directory: Path,
    client: Any | None = None,
    max_file_bytes: int = 20_000_000,
) -> None:
    if not isinstance(artifact, ChartArtifact):
        raise ChartPresentationError("A ChartArtifact is required")
    if (
        not isinstance(max_file_bytes, int)
        or isinstance(max_file_bytes, bool)
        or max_file_bytes < 1
    ):
        raise ChartPresentationError("max_file_bytes must be positive")
    root = Path(artifacts_directory).resolve(strict=True)
    chart_directory = root / artifact.session_id / "charts"
    expected_directory = chart_directory.resolve(strict=True)
    if expected_directory != chart_directory or chart_directory.is_symlink():
        raise ChartPresentationError("Unsafe chart directory")
    file_path = artifact.file_path
    metadata_path = artifact.metadata_path
    if file_path.parent != chart_directory or metadata_path.parent != chart_directory:
        raise ChartPresentationError("Artifact is outside its session directory")
    if file_path.is_symlink() or metadata_path.is_symlink():
        raise ChartPresentationError("Symbolic-link artifacts are not allowed")
    if not file_path.is_file() or not metadata_path.is_file():
        raise ChartPresentationError("Saved chart or metadata is missing")
    if file_path.stat().st_size > max_file_bytes or metadata_path.stat().st_size > 65536:
        raise ChartPresentationError("Saved chart exceeds the file size limit")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as error:
        raise ChartPresentationError("Invalid chart metadata") from error
    if not isinstance(metadata, dict) or any(
        metadata.get(key) != value
        for key, value in {
            "session_id": artifact.session_id,
            "library": artifact.library,
            "chart_type": artifact.chart_type,
            "media_type": artifact.media_type,
            "artifact_file": file_path.name,
        }.items()
    ):
        raise ChartPresentationError("Chart metadata does not match artifact")
    expected_media = "image/png" if artifact.library in {"matplotlib", "seaborn"} else "text/html"
    expected_suffix = ".png" if expected_media == "image/png" else ".html"
    if artifact.media_type != expected_media or file_path.suffix.lower() != expected_suffix:
        raise ChartPresentationError("Invalid artifact format")
    st = _streamlit_client(client)
    data = file_path.read_bytes()
    if expected_media == "image/png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ChartPresentationError("Invalid PNG artifact")
        st.image(data, caption=metadata.get("title", "Saved chart"), width="stretch")
    else:
        st.info(
            "Interactive HTML charts are available as downloads, not embedded in the application."
        )
        st.download_button(
            label="Download interactive chart",
            data=data,
            file_name=file_path.name,
            mime="text/html",
        )
