import hashlib
from pathlib import Path

from datapilot.ingestion.data_profiler import profile_dataframe
from datapilot.ingestion.file_loader import FileSource, load_data_file
from datapilot.knowledge.file_knowledge_writer import write_file_knowledge


def _file_fingerprint(source: FileSource) -> str:
    digest = hashlib.sha256()
    if isinstance(source, Path):
        if not source.is_file():
            raise FileNotFoundError(f"Data file not found: {source}")
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    else:
        position = source.tell()
        try:
            source.seek(0)
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        finally:
            source.seek(position)
    return digest.hexdigest()


def file_knowledge_cache_path(
    source: FileSource,
    knowledge_directory: Path,
    sheet_name: str | None = None,
) -> Path:
    filename = source.name if hasattr(source, "name") else str(source)
    extension = Path(filename).suffix.lower()
    if extension not in {".csv", ".xlsx"}:
        raise ValueError("Only CSV and XLSX files are supported")
    if extension == ".csv" and sheet_name is not None:
        raise ValueError("CSV files do not contain worksheets")
    if extension == ".xlsx" and not sheet_name:
        raise ValueError("An Excel worksheet must be selected")
    fingerprint = _file_fingerprint(source)
    identifier = hashlib.sha256(
        f"{extension}:{fingerprint}:{sheet_name or ''}".encode()
    ).hexdigest()
    return knowledge_directory / identifier / "profile.md"


def load_file_knowledge(
    source: FileSource,
    knowledge_directory: Path,
    sheet_name: str | None = None,
    refresh: bool = False,
) -> str:
    destination = file_knowledge_cache_path(source, knowledge_directory, sheet_name)
    if destination.is_file() and not refresh:
        return destination.read_text(encoding="utf-8")
    frame = load_data_file(source, sheet_name=sheet_name)
    profile = profile_dataframe(frame)
    write_file_knowledge(profile, destination)
    return destination.read_text(encoding="utf-8")
