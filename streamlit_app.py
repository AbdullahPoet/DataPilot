import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"
DATABASE_PATH = PROJECT_ROOT / "storage" / "app.db"

if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from datapilot.persistence.session_repository import create_session
from datapilot.ui.sidebar import render_sidebar


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
    title = f"{source_type} Analytics"
    try:
        session_id = create_session(DATABASE_PATH, title, configuration)
    except (OSError, ValueError) as error:
        st.error(f"Could not create session: {error}")
        return

    st.session_state.active_session_id = session_id
    st.session_state.session_config = configuration
    st.session_state.page = "chat"
    st.rerun()


def render_chat() -> None:
    configuration = st.session_state.get("session_config")
    if configuration is None:
        st.warning("No saved session configuration is available.")
        return
    st.title("Analytics Session")
    st.write(f"Data source: {configuration['source_type'].upper()}")
    st.write(f"Model mode: {configuration['llm_type'].capitalize()}")
    st.info("Session saved. Source and model connection settings will be added later.")


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
