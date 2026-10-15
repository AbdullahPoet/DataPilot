import streamlit as st


st.set_page_config(page_title="DataPilot", page_icon="📊", layout="wide")

with st.sidebar:
    st.title("DataPilot")
    if st.button("New Analytics", use_container_width=True):
        st.session_state.page = "configuration"

if "page" not in st.session_state:
    st.session_state.page = "home"

if st.session_state.page == "home":
    st.title("DataPilot")
    st.subheader("Agentic Data Analytics Workbench")
    st.write("Select New Analytics to configure a data source and an AI model.")
else:
    st.title("New Analytics")
    source = st.radio("Data source", ("SQL", "CSV", "XLSX"))
    model_mode = st.radio("Model mode", ("Local (Ollama)", "Cloud API"))
    st.info(f"Selected source: {source} | Selected model mode: {model_mode}")
    st.caption("Database connections, file uploads, and models will be added in later steps.")
