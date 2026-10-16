import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datapilot.reports.pdf_report import GeneratedReport


class ReportPresentationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SavedReport:
    path: Path
    session_id: str
    filename: str
    size_bytes: int


def _report_directory(reports_directory: Path, session_id: str) -> Path:
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", session_id):
        raise ReportPresentationError("Invalid session identifier")
    root = Path(reports_directory)
    if root.is_symlink() or root.exists() and not root.is_dir():
        raise ReportPresentationError("Invalid reports directory")
    directory = root / session_id
    if directory.is_symlink() or directory.exists() and not directory.is_dir():
        raise ReportPresentationError("Unsafe session reports directory")
    return directory


def _checked_pdf(path: Path, directory: Path, max_file_bytes: int) -> bytes:
    if not isinstance(max_file_bytes, int) or isinstance(max_file_bytes, bool) or max_file_bytes < 1:
        raise ReportPresentationError("max_file_bytes must be positive")
    if path.parent != directory or path.suffix.lower() != ".pdf" or path.is_symlink():
        raise ReportPresentationError("Invalid report file path")
    if not path.is_file():
        raise ReportPresentationError("Report file does not exist")
    if path.stat().st_size > max_file_bytes:
        raise ReportPresentationError("Report exceeds size limit")
    data = path.read_bytes()
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
        raise ReportPresentationError("Invalid PDF file")
    return data


def list_saved_reports(
    *,
    reports_directory: Path,
    session_id: str,
    max_file_bytes: int = 25_000_000,
) -> tuple[SavedReport, ...]:
    directory = _report_directory(reports_directory, session_id)
    if not directory.exists():
        return ()
    reports = []
    for path in directory.iterdir():
        if path.suffix.lower() != ".pdf" or path.is_symlink() or not path.is_file():
            continue
        try:
            _checked_pdf(path, directory, max_file_bytes)
        except (OSError, ReportPresentationError):
            continue
        reports.append(SavedReport(path, session_id, path.name, path.stat().st_size))
    return tuple(sorted(reports, key=lambda report: report.filename, reverse=True))


def present_saved_report(
    report: SavedReport | GeneratedReport,
    *,
    reports_directory: Path,
    client: Any | None = None,
    max_file_bytes: int = 25_000_000,
) -> None:
    if not isinstance(report, (SavedReport, GeneratedReport)):
        raise ReportPresentationError("A saved or generated report is required")
    directory = _report_directory(reports_directory, report.session_id)
    data = _checked_pdf(report.path, directory, max_file_bytes)
    if client is None:
        import streamlit as st

        client = st
    if callable(getattr(client, "pdf", None)):
        client.pdf(data, height=650)
    else:
        client.info("PDF preview is unavailable in this Streamlit version. Download the report to view it.")
    client.download_button(
        label="Download PDF report",
        data=data,
        file_name=report.path.name,
        mime="application/pdf",
    )
