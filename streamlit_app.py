import json
import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"
DATABASE_PATH = PROJECT_ROOT / "storage" / "app.db"
KNOWLEDGE_DIRECTORY = PROJECT_ROOT / "knowledge"

if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from datapilot.persistence.session_repository import create_session
from datapilot.persistence.sqlite_manager import open_database
from datapilot.ui.connection_form import render_connection_form
from datapilot.ingestion.file_loader import inspect_excel_sheets, load_data_file
from datapilot.knowledge.file_knowledge_cache import load_file_knowledge
from datapilot.ui.sidebar import render_sidebar


def save_source_configuration(session_id: str, configuration: dict[str, object]) -> None:
    serialized = json.dumps(configuration, allow_nan=False)
    with open_database(DATABASE_PATH) as connection:
        result = connection.execute(
            "UPDATE sessions SET configuration_json = ? WHERE session_id = ?",
            (serialized, session_id),
        )
        if result.rowcount != 1:
            raise LookupError("The selected session no longer exists")


def render_home() -> None:
    st.title("DataPilot")
    st.subheader("Agentic Data Analytics Workbench")
    st.write("Select New Analytics in the sidebar to configure a new analysis.")


def render_configuration() -> None:
    st.title("New Analytics")
    with st.form("new_analytics_configuration"):
        source_type = st.radio("Data source", ("SQL", "CSV", "XLSX"))
        model_mode = st.radio("Model mode", ("Local (Ollama)", "Cloud API"))
        submitted = st.form_submit_button("Create Analytics Session")

    if not submitted:
        return

    configuration = {
        "source_type": source_type.lower(),
        "llm_type": "local" if model_mode == "Local (Ollama)" else "cloud",
        "provider": "ollama" if model_mode == "Local (Ollama)" else None,
        "source_configured": False,
        "model_configured": False,
    }
    try:
        session_id = create_session(DATABASE_PATH, f"{source_type} Analytics", configuration)
    except (OSError, ValueError) as error:
        st.error(f"Could not create session: {error}")
        return

    st.session_state.active_session_id = session_id
    st.session_state.session_config = configuration
    st.session_state.page = "chat"
    st.rerun()



def render_file_workspace(configuration: dict[str, object], source_type: str) -> None:
    session_id = st.session_state.get("active_session_id")
    if not isinstance(session_id, str):
        st.error("No active session is available.")
        return

    st.subheader(f"{source_type.upper()} Data Source")
    saved_path = configuration.get("file_path")
    saved_sheet = configuration.get("sheet_name")
    if configuration.get("source_configured"):
        st.success("Saved data source configuration found.")
        st.write(f"File: {configuration.get('file_name', 'Unknown')}")
        if isinstance(saved_sheet, str):
            st.write(f"Worksheet: {saved_sheet}")
        frame = st.session_state.get(f"frame_{session_id}")
        if frame is not None:
            st.dataframe(frame.head(20), use_container_width=True)
        elif isinstance(saved_path, str) and st.button("Restore saved data", key=f"restore_{session_id}"):
            source = Path(saved_path)
            try:
                frame = load_data_file(source, sheet_name=saved_sheet if isinstance(saved_sheet, str) else None)
                knowledge = load_file_knowledge(
                    source, KNOWLEDGE_DIRECTORY / "files",
                    sheet_name=saved_sheet if isinstance(saved_sheet, str) else None,
                )
            except (OSError, ValueError, TypeError, ImportError, UnicodeError) as error:
                st.error(f"Could not restore saved data: {error}")
            else:
                st.session_state[f"frame_{session_id}"] = frame
                st.session_state[f"knowledge_{session_id}"] = knowledge
                st.rerun()

    method = st.radio("File location", ("Upload", "Local path", "Web URL"), key=f"{session_id}_location")
    if method == "Web URL":
        st.text_input("Web URL", key=f"{session_id}_web_url")
        st.info("Web URL retrieval is not implemented yet.")
        return

    source = None
    if method == "Upload":
        uploaded = st.file_uploader(
            "Choose a file", type=[source_type], accept_multiple_files=False,
            key=f"{session_id}_upload",
        )
        if uploaded is not None:
            source = uploaded
    else:
        path_text = st.text_input("Local file path", key=f"{session_id}_local_path")
        if path_text.strip():
            source = Path(path_text).expanduser()

    if source is None:
        return

    sheet_name = None
    if source_type == "xlsx":
        try:
            sheets = inspect_excel_sheets(source)
        except (OSError, ValueError, TypeError, ImportError) as error:
            st.error(f"Unable to inspect worksheets: {error}")
            return
        if not sheets:
            st.warning("No worksheets found.")
            return
        preferred = saved_sheet if isinstance(saved_sheet, str) and saved_sheet in sheets else sheets[0]
        sheet_name = st.selectbox(
            "Choose worksheet", sheets, index=sheets.index(preferred),
            key=f"{session_id}_sheet",
        )

    if not st.button("Load and profile data", key=f"{session_id}_load"):
        return

    try:
        frame = load_data_file(source, sheet_name=sheet_name)
        knowledge = load_file_knowledge(
            source, KNOWLEDGE_DIRECTORY / "files", sheet_name=sheet_name,
        )
        if isinstance(source, Path):
            persistent_path = source.resolve()
        else:
            source_directory = PROJECT_ROOT / "sessions" / session_id / "sources"
            source_directory.mkdir(parents=True, exist_ok=True)
            persistent_path = source_directory / f"source.{source_type}"
            persistent_path.write_bytes(source.getvalue())
    except (OSError, ValueError, TypeError, ImportError, UnicodeError) as error:
        st.error(f"Unable to load or save the data: {error}")
        return

    updated = {
        **configuration,
        "source_configured": True,
        "file_name": source.name if isinstance(source, Path) else source.name,
        "file_path": str(persistent_path),
        "sheet_name": sheet_name,
    }
    try:
        save_source_configuration(session_id, updated)
    except (OSError, LookupError, ValueError, TypeError) as error:
        st.error(f"Unable to save source configuration: {error}")
        return

    st.session_state.session_config = updated
    st.session_state[f"frame_{session_id}"] = frame
    st.session_state[f"knowledge_{session_id}"] = knowledge
    st.success("File source and selected worksheet saved to this session.")
    st.dataframe(frame.head(20), use_container_width=True)
    st.text_area("Verified file knowledge", value=knowledge, height=250, disabled=True)


def render_chat() -> None:
    configuration = st.session_state.get("session_config")
    if not isinstance(configuration, dict):
        st.warning("No saved session configuration is available.")
        return

    st.title("Analytics Session")
    source_type = configuration.get("source_type")
    st.write(f"Data source: {str(source_type).upper()}")
    st.write(f"Model mode: {str(configuration.get('llm_type')).capitalize()}")

    if source_type in {"csv", "xlsx"}:
        render_file_workspace(configuration, source_type)
        return
    if source_type != "sql":
        st.error("Unsupported data source configuration.")
        return

    if configuration.get("source_configured"):
        st.success("The saved database source was verified previously.")
        st.write(f"Dialect: {configuration.get('database_dialect')}")
        st.write(f"Database: {configuration.get('database_name')}")
        st.caption("Reconnect to verify access or refresh database understanding.")
    else:
        st.info("Connect to your database to load its verified schema.")

    connection_info = render_connection_form(KNOWLEDGE_DIRECTORY)
    if connection_info is None:
        return

    session_id = st.session_state.get("active_session_id")
    if not isinstance(session_id, str):
        st.error("No active session is available.")
        return

    updated_config = {
        **configuration,
        "source_configured": True,
        "database_dialect": connection_info.dialect,
        "database_name": connection_info.database,
        "database_driver": connection_info.driver,
    }
    try:
        save_source_configuration(session_id, updated_config)
    except (OSError, LookupError, ValueError) as error:
        st.error(f"Could not save database configuration: {error}")
        return

    st.session_state.session_config = updated_config
    st.success("Database details saved to this session without credentials.")


def main() -> None:
    st.set_page_config(page_title="DataPilot", page_icon="📊", layout="wide")
    if "page" not in st.session_state:
        st.session_state.page = "home"
    render_sidebar(DATABASE_PATH)
    if st.session_state.page == "configuration":
        render_configuration()
    elif st.session_state.page == "chat":
        render_chat()
    else:
        render_home()


if __name__ == "__main__":
    main()
