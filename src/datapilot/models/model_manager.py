import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class ModelResponse:
    content: str
    model: str
    provider: str


PROVIDER_ENDPOINTS = {
    "OpenAI": "https://api.openai.com/v1/chat/completions",
    "DeepSeek": "https://api.deepseek.com/chat/completions",
    "Qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
    "Anthropic (Claude)": "https://api.anthropic.com/v1/messages",
}


class ModelRequestError(RuntimeError):
    pass


def _endpoint(configuration: Mapping[str, str | int]) -> str:
    provider = str(configuration["provider"])
    if provider == "ollama":
        base_url = str(configuration.get("base_url", "http://localhost:11434")).rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Invalid Ollama endpoint")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Ollama endpoint cannot contain credentials or query parameters")
        return f"{base_url}/api/chat"
    if provider == "Custom OpenAI-compatible":
        base_url = str(configuration["base_url"]).rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Custom API endpoint must use HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Custom API endpoint cannot contain credentials or query parameters")
        return f"{base_url}/chat/completions"
    if provider not in PROVIDER_ENDPOINTS:
        raise ValueError(f"Unsupported provider: {provider}")
    return PROVIDER_ENDPOINTS[provider]


def _parse_response(data: object, provider: str) -> str:
    if not isinstance(data, dict):
        raise ModelRequestError("Model returned an invalid response")
    if provider == "ollama":
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
    elif provider == "Anthropic (Claude)":
        blocks = data.get("content")
        content = "\n".join(
            block["text"] for block in blocks
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        ) if isinstance(blocks, list) else None
    else:
        choices = data.get("choices")
        message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ModelRequestError("Model returned no text content")
    return content


def invoke_model(
    configuration: Mapping[str, str | int],
    messages: Sequence[ChatMessage],
    *,
    max_output_tokens: int = 2048,
    timeout: float = 60.0,
) -> ModelResponse:
    load_dotenv()
    if not messages or max_output_tokens <= 0 or timeout <= 0:
        raise ValueError("Messages, output token limit, and timeout must be valid")
    provider = str(configuration["provider"])
    model = str(configuration["model"])
    if not model.strip():
        raise ValueError("Model identifier is required")
    endpoint = _endpoint(configuration)
    headers = {"Content-Type": "application/json"}
    chat = [{"role": message.role, "content": message.content} for message in messages]
    if provider == "ollama":
        context_window = int(configuration.get("context_window", 35000))
        if context_window < 35000:
            raise ValueError("Configured context window must be at least 35,000 tokens")
        payload = {
            "model": model,
            "messages": chat,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": context_window, "num_predict": max_output_tokens},
        }
    else:
        secret_name = str(configuration.get("credential_env_var", ""))
        if not secret_name:
            raise ValueError("Cloud credential environment variable is required")
        api_key = os.getenv(secret_name)
        if not api_key:
            raise ValueError(f"Missing cloud API credential: {secret_name}")
        if provider == "Anthropic (Claude)":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
            system_text = "\n".join(message.content for message in messages if message.role == "system")
            payload = {
                "model": model,
                "messages": [message for message in chat if message["role"] != "system"],
                "max_tokens": max_output_tokens,
                "temperature": 0,
            }
            if system_text:
                payload["system"] = system_text
        else:
            headers["Authorization"] = f"Bearer {api_key}"
            payload = {"model": model, "messages": chat, "max_tokens": max_output_tokens, "temperature": 0}
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            response_data = json.load(response)
    except HTTPError as error:
        raise ModelRequestError(f"Model API returned HTTP {error.code}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise ModelRequestError("Unable to reach the selected model endpoint") from error
    except (ValueError, UnicodeError) as error:
        raise ModelRequestError("Model API returned invalid JSON") from error
    return ModelResponse(content=_parse_response(response_data, provider), model=model, provider=provider)
