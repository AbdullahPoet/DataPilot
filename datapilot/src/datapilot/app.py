import streamlit as st


SOURCE_TYPES = ("SQL Database", "CSV", "XLSX")
MODEL_MODES = ("Local (Ollama)", "Cloud API")
CLOUD_PROVIDERS = ("OpenAI", "Claude", "DeepSeek", "Qwen", "Custom OpenAI-compatible API")
DEFAULT_CONTEXT_TOKENS = 35_000
MIN_CONTEXT_TOKENS = 35_000


def start_new_analytics() -> None:
    st.session_state["active_view"] = "configuration"
    st.session_state.pop("configuration_preview", None)


def show_home() -> None:
    st.title("DataPilot")
    st.subheader("Agentic Data Analytics Workbench")
    st.write("Select **New Analytics** in the sidebar to configure a new analysis.")


def show_configuration() -> None:
    st.title("New Analytics")
    st.write("Choose a data source and an LLM before starting a new session.")

    source_type = st.radio("Data source", SOURCE_TYPES, horizontal=True)
    model_mode = st.radio("LLM runtime", MODEL_MODES, horizontal=True)

    model_config: dict[str, str | int] = {"mode": model_mode}

    if model_mode == "Local (Ollama)":
        context_mode = st.radio(
            "Local model context window",
            ("I don't know (use 35,000 tokens)", "Enter token count"),
        )
        context_tokens = DEFAULT_CONTEXT_TOKENS
        if context_mode == "Enter token count":
            context_tokens = st.number_input(
                "Context window size (tokens)",
                min_value=MIN_CONTEXT_TOKENS,
                value=DEFAULT_CONTEXT_TOKENS,
                step=1_000,
            )
        model_config["context_tokens"] = int(context_tokens)
        st.caption("The Ollama backend must support the configured context size.")
    else:
        provider = st.selectbox("Cloud provider", CLOUD_PROVIDERS)
        model_config["provider"] = provider
        st.caption("Cloud API credentials will be loaded from .env, not entered here.")

    if st.button("Review selections", type="primary"):
        st.session_state["configuration_preview"] = {
            "source_type": source_type,
            "model": model_config,
        }

    preview = st.session_state.get("configuration_preview")
    if preview is not None:
        st.subheader("Configuration preview")
        st.json(preview)
        st.info(
            "This is a UI preview only. Source connections, model selection, "
            "and SQLite session persistence will be added in subsequent steps."
        )


def main() -> None:
    st.set_page_config(page_title="DataPilot", layout="wide")

    with st.sidebar:
        st.header("DataPilot")
        st.button(
            "New Analytics",
            on_click=start_new_analytics,
            use_container_width=True,
        )

    if st.session_state.get("active_view", "home") == "configuration":
        show_configuration()
        return

    show_home()


if __name__ == "__main__":
    main()
