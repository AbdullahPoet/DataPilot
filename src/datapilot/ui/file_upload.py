from pathlib import Path

import pandas as pd
import streamlit as st

from datapilot.ingestion.file_loader import inspect_excel_sheets, load_data_file
from datapilot.knowledge.file_knowledge_cache import load_file_knowledge


def render_file_upload(
    source_type: str,
    knowledge_directory: Path,
) -> tuple[pd.DataFrame, str] | None:
    if source_type not in {"csv", "xlsx"}:
        raise ValueError("File source must be CSV or XLSX")

    st.subheader(f"{source_type.upper()} Data Source")
    method = st.radio(
        "File location",
        ("Upload", "Local path", "Web URL"),
        key=f"{source_type}_location_method",
    )

    if method == "Web URL":
        st.text_input("Web URL", key=f"{source_type}_web_url")
        st.info("Web URL retrieval is not implemented yet. Use upload or local path.")
        return None

    if method == "Upload":
        source = st.file_uploader(
            "Choose a file",
            type=[source_type],
            accept_multiple_files=False,
            key=f"{source_type}_upload",
        )
    else:
        path_text = st.text_input(
            "Local file path",
            key=f"{source_type}_local_path",
        )
        source = Path(path_text).expanduser() if path_text.strip() else None

    if source is None:
        return None

    sheet_name = None
    if source_type == "xlsx":
        try:
            sheets = inspect_excel_sheets(source)
        except (OSError, ValueError, TypeError, ImportError) as error:
            st.error(f"Unable to inspect Excel worksheets: {error}")
            return None
        if not sheets:
            st.warning("This workbook contains no worksheets.")
            return None
        sheet_name = st.selectbox("Choose worksheet", sheets)

    if not st.button("Load and profile data", key=f"{source_type}_load"):
        return None

    try:
        frame = load_data_file(source, sheet_name=sheet_name)
        knowledge = load_file_knowledge(
            source,
            knowledge_directory,
            sheet_name=sheet_name,
        )
    except (OSError, ValueError, TypeError, ImportError, UnicodeError, pd.errors.ParserError) as error:
        st.error(f"Unable to load or profile the file: {error}")
        return None

    st.success("Data loaded and profiled successfully.")
    st.dataframe(frame.head(20), use_container_width=True)
    st.text_area("Verified file knowledge", value=knowledge, height=250, disabled=True)
    return frame, knowledge
