import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


class PDFReportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReportData:
    title: str
    session_id: str
    question: str
    summary: str
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    source_id: str
    executed_query: str = ""
    chart_paths: tuple[Path, ...] = ()
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class GeneratedReport:
    path: Path
    session_id: str
    created_at: str
    displayed_rows: int


def _validated(data: ReportData, max_rows: int) -> None:
    if not isinstance(data, ReportData):
        raise PDFReportError("ReportData is required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", data.session_id):
        raise PDFReportError("Invalid session identifier")
    if not all(isinstance(value, str) and value.strip() for value in (data.title, data.question, data.summary, data.source_id)):
        raise PDFReportError("Title, question, summary and source must be nonempty")
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= 1000:
        raise PDFReportError("max_rows must be between 1 and 1000")
    if not data.columns or len(set(data.columns)) != len(data.columns):
        raise PDFReportError("Unique result columns are required")
    if any(not isinstance(column, str) or not column.strip() for column in data.columns):
        raise PDFReportError("Invalid result column")
    if any(len(row) != len(data.columns) for row in data.rows):
        raise PDFReportError("Result row width does not match columns")
    if len(data.chart_paths) > 12:
        raise PDFReportError("At most 12 charts are supported")


def _paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    text = "" if value is None else str(value)
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _chart_image(path: Path, available_width: float) -> Image:
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg"} or not path.is_file() or path.is_symlink():
        raise PDFReportError("Charts must be existing PNG or JPEG files")
    if path.stat().st_size > 10 * 1024 * 1024:
        raise PDFReportError("Chart exceeds the 10 MB limit")
    try:
        reader = ImageReader(str(path))
        width, height = reader.getSize()
    except Exception as error:
        raise PDFReportError("Cannot read chart image") from error
    if width < 1 or height < 1:
        raise PDFReportError("Chart dimensions are invalid")
    scale = min(available_width / width, 360 / height, 1)
    return Image(str(path), width=width * scale, height=height * scale)


def generate_pdf_report(
    data: ReportData,
    *,
    reports_directory: Path,
    max_rows: int = 100,
) -> GeneratedReport:
    _validated(data, max_rows)
    directory = Path(reports_directory) / data.session_id
    if Path(reports_directory).is_symlink() or directory.is_symlink():
        raise PDFReportError("Report directories cannot be symbolic links")
    directory.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC).isoformat()
    slug = re.sub(r"[^a-z0-9]+", "_", data.title.lower()).strip("_")[:48] or "analysis"
    filename = f"{datetime.now(UTC):%Y%m%dT%H%M%S}_{slug}_{uuid4().hex[:12]}.pdf"
    destination = directory / filename
    styles = getSampleStyleSheet()
    heading = styles["Heading2"]
    body = styles["BodyText"]
    cell_style = ParagraphStyle("DataPilotCell", parent=body, fontSize=8, leading=11)
    title_style = ParagraphStyle("DataPilotTitle", parent=styles["Title"], alignment=TA_CENTER)
    fd, temporary = tempfile.mkstemp(prefix=".report_", suffix=".pdf", dir=directory)
    os.close(fd)
    try:
        document = SimpleDocTemplate(
            temporary,
            pagesize=(595.28, 841.89),
            leftMargin=45,
            rightMargin=45,
            topMargin=45,
            bottomMargin=45,
        )
        available_width = document.width
        story = [
            _paragraph(data.title, title_style),
            Spacer(1, 12),
            _paragraph(f"Generated (UTC): {created_at}", body),
            _paragraph(f"Session: {data.session_id} | Source: {data.source_id}", body),
            Spacer(1, 12),
            _paragraph("Analytical Question", heading),
            _paragraph(data.question, body),
            Spacer(1, 10),
            _paragraph("Findings", heading),
            _paragraph(data.summary, body),
            Spacer(1, 10),
            _paragraph("Result Preview", heading),
        ]
        shown = data.rows[:max_rows]
        columns_count = len(data.columns)
        if columns_count > 10:
            raise PDFReportError("PDF preview supports at most 10 columns")
        table_rows = [[_paragraph(name, cell_style) for name in data.columns]]
        table_rows.extend([_paragraph(value, cell_style) for value in row] for row in shown)
        table = Table(table_rows, colWidths=[available_width / columns_count] * columns_count, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7ECF2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D3DBE3")),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(table)
        if data.truncated or len(data.rows) > max_rows:
            story.extend([Spacer(1, 8), _paragraph("Result preview is truncated; not all records are shown.", body)])
        if data.executed_query.strip():
            story.extend([
                Spacer(1, 12),
                _paragraph("Executed Query", heading),
                _paragraph(data.executed_query, body),
            ])
        for index, path in enumerate(data.chart_paths, start=1):
            story.extend([
                Spacer(1, 12),
                _paragraph(f"Chart {index}", heading),
                _chart_image(Path(path), available_width),
            ])
        document.build(story)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return GeneratedReport(destination, data.session_id, created_at, len(shown))
