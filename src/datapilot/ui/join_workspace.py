import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from datapilot.ingestion.file_loader import inspect_excel_sheets, load_data_file
from datapilot.ingestion.joined_source import join_frames, load_joined_source


def render_join_workspace(
    root: Path, session_id: str, configuration: dict[str, Any]
) -> dict | None:
    st.subheader("Combine files")
    st.caption(
        "Join two to eight CSV/XLSX files in order. Columns use source aliases. "
        "Null keys never match. Preview the keys and row counts before saving."
    )
    method = st.radio(
        "Joined file location",
        ["Upload", "Local paths"],
        index=1 if configuration.get("files") else 0,
        key=f"join_method_{session_id}",
    )
    if method == "Upload":
        sources = st.file_uploader(
            "Choose files to join",
            type=["csv", "xlsx"],
            accept_multiple_files=True,
            key=f"join_upload_{session_id}",
        )
    else:
        default = "\n".join(source["path"] for source in configuration.get("files", []))
        paths = st.text_area(
            "Local paths, one per line", value=default, key=f"join_paths_{session_id}"
        )
        sources = [Path(line.strip()).expanduser() for line in paths.splitlines() if line.strip()]
    if not 2 <= len(sources) <= 8:
        st.info("Select between two and eight files to configure joins.")
        return None
    files = []
    frames = []
    try:
        for index, source in enumerate(sources):
            saved = configuration.get("files", [])
            previous = saved[index] if index < len(saved) else {}
            alias = st.text_input(
                f"Alias for {source.name}",
                value=previous.get("alias", f"file{index + 1}"),
                key=f"join_alias_{session_id}_{index}",
            )
            sheet = None
            if Path(source.name).suffix.lower() == ".xlsx":
                sheets = inspect_excel_sheets(source)
                preferred = previous.get("sheet_name")
                sheet = st.selectbox(
                    f"Worksheet in {source.name}",
                    sheets,
                    index=sheets.index(preferred) if preferred in sheets else 0,
                    key=f"join_sheet_{session_id}_{index}",
                )
            frame = load_data_file(source, sheet_name=sheet)
            if len(frame) > 1_000_000:
                raise ValueError("File exceeds the input row limit")
            frames.append(frame.add_prefix(alias + "."))
            if isinstance(source, Path):
                path = source.resolve()
            else:
                directory = root / "sessions" / session_id / "sources"
                if any(p.is_symlink() for p in (root / "sessions", directory.parent, directory)):
                    raise ValueError("Source directories cannot be symbolic links")
                directory.mkdir(parents=True, exist_ok=True)
                content = source.getvalue()
                path = directory / (
                    hashlib.sha256(content).hexdigest() + Path(source.name).suffix.lower()
                )
                if path.is_symlink():
                    raise ValueError("Source files cannot be symbolic links")
                if not path.exists():
                    path.write_bytes(content)
            files.append({"path": str(path), "alias": alias, "sheet_name": sheet})
        frame = frames[0]
        joins = []
        for index, right in enumerate(frames[1:], start=1):
            saved_joins = configuration.get("joins", [])
            previous_join = saved_joins[index - 1] if index - 1 < len(saved_joins) else {}
            left_options, right_options = list(frame.columns), list(right.columns)
            st.write(f"Join {files[index]['alias']}")
            left_on = st.selectbox(
                "Left key",
                left_options,
                index=left_options.index(previous_join["left_on"])
                if previous_join.get("left_on") in left_options
                else 0,
                key=f"join_left_{session_id}_{index}",
            )
            right_on = st.selectbox(
                "Right key",
                right_options,
                index=right_options.index(previous_join["right_on"])
                if previous_join.get("right_on") in right_options
                else 0,
                key=f"join_right_{session_id}_{index}",
            )
            how = st.selectbox(
                "Join type",
                ["left", "inner"],
                index=1 if previous_join.get("how") == "inner" else 0,
                key=f"join_how_{session_id}_{index}",
            )
            relationships = ["many_to_one", "one_to_one", "one_to_many", "many_to_many"]
            relationship = st.selectbox(
                "Key relationship",
                relationships,
                index=relationships.index(previous_join.get("relationship", "many_to_one")),
                key=f"join_relationship_{session_id}_{index}",
            )
            spec = {
                "right_alias": files[index]["alias"],
                "left_on": left_on,
                "right_on": right_on,
                "how": how,
                "relationship": relationship,
            }
            joins.append(spec)
            frame, diagnostics = join_frames(
                frame,
                right,
                left_on=left_on,
                right_on=right_on,
                how=how,
                relationship=relationship,
            )
            st.json(diagnostics)
            if diagnostics["unmatched_left_rows"] or diagnostics["unmatched_right_rows"]:
                st.warning("Some keys do not match. Review the unmatched row counts above.")
            if relationship == "many_to_many":
                st.warning(
                    "Many-to-many joins can multiply amounts. Confirm this relationship is intended."
                )
        st.dataframe(frame.head(20), width="stretch")
        if st.button("Save joined data source", key=f"save_join_{session_id}"):
            updated = {**configuration, "files": files, "joins": joins, "source_configured": True}
            updated.pop("file_path", None)
            updated.pop("sheet_name", None)
            verified = load_joined_source(updated)
            st.session_state[f"frame_{session_id}"] = verified.dataframe
            return updated
    except (ValueError, TypeError, OSError, KeyError, ImportError, pd.errors.ParserError) as error:
        st.error(f"Could not prepare join: {error}")
    return None
