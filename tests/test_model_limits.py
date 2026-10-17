import pytest

from datapilot.models.model_manager import (
    ChatMessage,
    ModelRequestError,
    _parse_response,
    invoke_model,
)


@pytest.mark.parametrize("timeout", [0, -1, 601])
def test_invalid_model_timeout_is_rejected(timeout: int) -> None:
    with pytest.raises(ValueError, match="timeout"):
        invoke_model(
            {"provider": "ollama", "model": "test", "request_timeout": timeout},
            [ChatMessage("user", "Hello")],
        )


def test_oversized_model_context_is_rejected_before_network_access() -> None:
    with pytest.raises(ValueError, match="context budget"):
        invoke_model({"provider": "ollama", "model": "test"}, [ChatMessage("user", "A" * 35000)])


def test_reasoning_is_not_accepted_as_final_model_output() -> None:
    with pytest.raises(ModelRequestError, match="without a final answer"):
        _parse_response(
            {"message": {"content": "", "thinking": "An unfinished reasoning trace"}}, "ollama"
        )
