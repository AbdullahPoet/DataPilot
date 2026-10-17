from pathlib import Path
from typing import BinaryIO

import pandas as pd

FileSource = Path | BinaryIO
SUPPORTED_EXTENSIONS = frozenset({".csv", ".xlsx"})


def _extension(source: FileSource) -> str:
    filename = source.name if hasattr(source, "name") else str(source)
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {extension or '(none)'}")
    return extension


def _prepare_source(source: FileSource) -> FileSource:
    if isinstance(source, Path):
        if not source.is_file():
            raise FileNotFoundError(f"Data file not found: {source}")
        return source
    if not hasattr(source, "read") or not hasattr(source, "seek"):
        raise TypeError("File source must be a Path or seekable binary file")
    source.seek(0)
    return source


def inspect_excel_sheets(source: FileSource) -> list[str]:
    if _extension(source) != ".xlsx":
        raise ValueError("Worksheet inspection requires an .xlsx file")
    prepared = _prepare_source(source)
    with pd.ExcelFile(prepared, engine="openpyxl") as workbook:
        return list(workbook.sheet_names)


def load_data_file(source: FileSource, sheet_name: str | None = None) -> pd.DataFrame:
    extension = _extension(source)
    prepared = _prepare_source(source)
    if extension == ".csv":
        if sheet_name is not None:
            raise ValueError("CSV files do not contain worksheets")
        return pd.read_csv(prepared)
    if sheet_name is None:
        raise ValueError("Select an Excel worksheet before loading data")
    with pd.ExcelFile(prepared, engine="openpyxl") as workbook:
        if sheet_name not in workbook.sheet_names:
            raise ValueError(f"Excel worksheet not found: {sheet_name}")
        return pd.read_excel(workbook, sheet_name=sheet_name)
