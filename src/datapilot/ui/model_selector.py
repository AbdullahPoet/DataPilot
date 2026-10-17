import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import streamlit as st
from dotenv import load_dotenv

CLOUD_PROVIDERS = {
    "OpenAI": "OPENAI_API_KEY",
    "Anthropic (Claude)": "ANTHROPIC_API_KEY",
    "DeepSeek": "DEEPSEEK_API_KEY",
    "Qwen": "DASHSCOPE_API_KEY",
    "Custom OpenAI-compatible": "CUSTOM_LLM_API_KEY",
}


def _ollama_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a valid Ollama HTTP endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Ollama endpoint must not contain credentials or query parameters")
    return base_url.rstrip("/")


def inspect_ollama_model(base_url: str, model: str, timeout: float = 5.0) -> dict[str, object]:
    request = Request(
        f"{_ollama_url(base_url)}/api/show",
        data=json.dumps({"model": model}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise ConnectionError("Unable to inspect the selected Ollama model") from error
    if not isinstance(data, dict):
        raise TypeError("Ollama returned invalid model capabilities")
    return data


def discover_ollama_models(base_url: str, timeout: float = 5.0) -> list[str]:
    endpoint = f"{_ollama_url(base_url)}/api/tags"
    try:
        with urlopen(endpoint, timeout=timeout) as response:
            data = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise ConnectionError("Unable to retrieve models from Ollama") from error
    if not isinstance(data, dict):
        raise TypeError("Ollama returned an invalid model list")
    if not isinstance(data.get("models"), list):
        raise TypeError("Ollama returned an invalid model list")
    models = data["models"]
    return sorted(
        {
            item["name"]
            for item in models
            if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"]
        }
    )


def render_model_selector() -> dict[str, str | int] | None:
    load_dotenv()
    mode = st.radio("Inference mode", ("Local (Ollama)", "Cloud API"), key="model_mode")
    if mode == "Local (Ollama)":
        endpoint = st.text_input(
            "Ollama endpoint", value="http://localhost:11434", key="ollama_endpoint"
        ).strip()
        if not endpoint:
            st.warning("Enter the Ollama endpoint.")
            return None
        try:
            models = discover_ollama_models(endpoint)
        except (ConnectionError, ValueError, TypeError) as error:
            st.error(str(error))
            return None
        if not models:
            st.warning("No Ollama models are installed.")
            return None
        model = st.selectbox("Installed model", models, key="ollama_model")
        try:
            capabilities = inspect_ollama_model(endpoint, model)
        except (ConnectionError, ValueError, TypeError) as error:
            st.error(str(error))
            return None
        size = st.radio("Context window", ("I don't know (35,000)", "Custom"), key="context_choice")
        context_window = (
            35000
            if size.startswith("I don't")
            else st.number_input(
                "Context window in tokens",
                min_value=1,
                value=35000,
                step=1024,
                key="context_tokens",
            )
        )
        if context_window < 35000:
            st.warning("DataPilot requires a configured context of at least 35,000 tokens.")
            return None
        st.caption("The configured window must also be supported by the Ollama model and runtime.")
        configuration = {
            "llm_type": "local",
            "provider": "ollama",
            "model": str(model),
            "base_url": endpoint,
            "context_window": int(context_window),
            "request_timeout": int(
                st.number_input(
                    "Model request timeout (seconds)",
                    min_value=1,
                    max_value=600,
                    value=180,
                    key="ollama_timeout",
                )
            ),
        }
        limits = capabilities.get("model_info", {})
        maximum = (
            [
                value
                for name, value in limits.items()
                if name.endswith(".context_length") and isinstance(value, int)
            ]
            if isinstance(limits, dict)
            else []
        )
        if maximum and context_window > max(maximum):
            st.error("The configured context exceeds the selected model's advertised maximum.")
            return None
        thinking = capabilities.get("thinking")
        if isinstance(thinking, dict) and False in thinking.get("values", []):
            configuration["think"] = st.checkbox(
                "Enable model reasoning", value=False, key="ollama_thinking"
            )
        return configuration

    provider = st.selectbox("Cloud provider", list(CLOUD_PROVIDERS), key="cloud_provider")
    model = st.text_input("Model identifier", key="cloud_model").strip()
    if not model:
        st.info("Enter the exact model identifier for your provider.")
        return None
    secret_name = CLOUD_PROVIDERS[provider]
    if not os.getenv(secret_name):
        st.warning(f"Set {secret_name} in your .env file or process environment.")
        return None
    configuration: dict[str, str | int] = {
        "llm_type": "cloud",
        "provider": provider,
        "model": model,
        "credential_env_var": secret_name,
    }
    if provider == "Custom OpenAI-compatible":
        endpoint = st.text_input("API base URL", key="cloud_base_url").strip()
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            st.warning("Enter a valid HTTPS API base URL without embedded credentials.")
            return None
        configuration["base_url"] = endpoint
    return configuration
