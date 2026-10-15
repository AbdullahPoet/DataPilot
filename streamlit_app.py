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


def render_chat() -> None:
    configuration = st.session_state.get("session_config")
    if not isinstance(configuration, dict):
        st.warning("No saved session configuration is available.")
        return

    st.title("Analytics Session")
    source_type = configuration.get("source_type")
    st.write(f"Data source: {str(source_type).upper()}")
    st.write(f"Model mode: {str(configuration.get('llm_type')).capitalize()}")

    if source_type != "sql":
        st.info("File source configuration will be available in a later step.")
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
