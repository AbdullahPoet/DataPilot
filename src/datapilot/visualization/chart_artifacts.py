import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from datapilot.visualization.chart_renderer import RenderedChart


class ChartArtifactError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ChartArtifact:
    session_id: str
    library: str
    chart_type: str
    file_path: Path
    metadata_path: Path
    media_type: str
    row_count: int
    created_at: str


def _safe_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", session_id):
        raise ChartArtifactError("Invalid session identifier")
    return session_id


def _safe_title(title: str) -> str:
    if not isinstance(title, str) or not title.strip():
        raise ChartArtifactError("Chart title cannot be empty")
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:64]
    return slug or "chart"


def _atomic_write(target: Path, content: bytes) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=".chart_", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _render_content(chart: RenderedChart) -> tuple[bytes, str, str]:
    if chart.library in {"matplotlib", "seaborn"}:
        from io import BytesIO

        from matplotlib.figure import Figure

        if not isinstance(chart.figure, Figure):
            raise ChartArtifactError("Expected a Matplotlib figure")
        buffer = BytesIO()
        chart.figure.savefig(buffer, format="png", dpi=150)
        return buffer.getvalue(), ".png", "image/png"
    if chart.library == "plotly":
        from plotly.graph_objects import Figure

        if not isinstance(chart.figure, Figure):
            raise ChartArtifactError("Expected a Plotly figure")
        return chart.figure.to_html(full_html=True, include_plotlyjs=True).encode("utf-8"), ".html", "text/html"
    if chart.library == "bokeh":
        from bokeh.embed import file_html
        from bokeh.models import Model
        from bokeh.resources import INLINE

        if not isinstance(chart.figure, Model):
            raise ChartArtifactError("Expected a Bokeh model")
        return file_html(chart.figure, INLINE, title="DataPilot Chart").encode("utf-8"), ".html", "text/html"
    raise ChartArtifactError("Unsupported chart library")


def save_chart_artifact(
    chart: RenderedChart,
    *,
    artifacts_directory: Path,
    session_id: str,
    title: str,
) -> ChartArtifact:
    if not isinstance(chart, RenderedChart):
        raise ChartArtifactError("A RenderedChart is required")
    if chart.row_count < 1:
        raise ChartArtifactError("Chart must contain observations")
    safe_id = _safe_session_id(session_id)
    safe_title = _safe_title(title)
    directory = Path(artifacts_directory) / safe_id / "charts"
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ChartArtifactError("Chart directory cannot be a symbolic link")
    content, extension, media_type = _render_content(chart)
    if not content:
        raise ChartArtifactError("Rendered chart is empty")
    created_at = datetime.now(UTC).isoformat()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    stem = f"{timestamp}_{safe_title}_{uuid4().hex[:12]}"
    file_path = directory / f"{stem}{extension}"
    metadata_path = directory / f"{stem}.json"
    metadata: dict[str, Any] = {
        "session_id": safe_id,
        "library": chart.library,
        "chart_type": chart.chart_type,
        "row_count": chart.row_count,
        "title": title,
        "media_type": media_type,
        "created_at": created_at,
        "artifact_file": file_path.name,
    }
    _atomic_write(file_path, content)
    try:
        _atomic_write(metadata_path, json.dumps(metadata, indent=2, ensure_ascii=False).encode("utf-8"))
    except Exception:
        file_path.unlink(missing_ok=True)
        raise
    return ChartArtifact(
        session_id=safe_id,
        library=chart.library,
        chart_type=chart.chart_type,
        file_path=file_path,
        metadata_path=metadata_path,
        media_type=media_type,
        row_count=chart.row_count,
        created_at=created_at,
    )
