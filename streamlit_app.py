import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"
DATABASE_PATH = PROJECT_ROOT / "storage" / "app.db"

if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from datapilot.ui.sidebar import render_sidebar


def render_home() -> None:
    st.title("DataPilot")
    st.subheader("Agentic Data Analytics Workbench")
    st.write("Select New Analytics in the sidebar to configure a new analysis.")


def render_configuration() -> None:
    st.title("New Analytics")
    source = st.radio("Data source", ("SQL", "CSV", "XLSX"))
    model_mode = st.radio("Model mode", ("Local (Ollama)", "Cloud API"))
    st.info(f"Selected source: {source} | Selected model mode: {model_mode}")
    st.caption("Saving configuration and connecting data sources will be added next.")


def render_chat() -> None:
    session = st.session_state.get("session_config")
    if session is None:
        st.warning("No saved session configuration is available.")
        return
    st.title("Analytics Session")
    st.info("Session restored. Chat and analysis execution will be added later.")


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
