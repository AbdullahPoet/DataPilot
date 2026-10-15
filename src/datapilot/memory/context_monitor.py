from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import isfinite


DEFAULT_CONTEXT_WINDOW = 35_000
COMPACTION_THRESHOLD = 0.85


@dataclass(frozen=True)
class ContextUsage:
    context_window: int
    input_tokens: int
    reserved_output_tokens: int
    total_tokens: int
    utilization: float
    should_compact: bool
    available_tokens: int


def resolve_context_window(configured_tokens: int | None) -> int:
    if configured_tokens is None:
        return DEFAULT_CONTEXT_WINDOW
    if isinstance(configured_tokens, bool) or not isinstance(configured_tokens, int):
        raise TypeError("Context window must be an integer")
    if configured_tokens < DEFAULT_CONTEXT_WINDOW:
        raise ValueError("Configured context window must be at least 35,000 tokens")
    return configured_tokens


def count_message_tokens(
    messages: Sequence[str],
    tokenizer: Callable[[str], Sequence[int]],
    *,
    tokens_per_message: int = 0,
) -> int:
    if isinstance(tokens_per_message, bool) or tokens_per_message < 0:
        raise ValueError("Message overhead must be nonnegative")
    total = 0
    for message in messages:
        if not isinstance(message, str):
            raise TypeError("Messages must contain text")
        total += len(tokenizer(message)) + tokens_per_message
    return total


def assess_context(
    input_tokens: int,
    reserved_output_tokens: int,
    *,
    context_window: int | None = None,
    threshold: float = COMPACTION_THRESHOLD,
) -> ContextUsage:
    window = resolve_context_window(context_window)
    for label, value in (
        ("Input token count", input_tokens),
        ("Reserved output token count", reserved_output_tokens),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{label} must be a nonnegative integer")
    if isinstance(threshold, bool) or not isinstance(threshold, (float, int)):
        raise ValueError("Threshold must be a number between 0 and 1")
    if not isfinite(threshold) or not 0 < threshold < 1:
        raise ValueError("Threshold must be a number between 0 and 1")
    total = input_tokens + reserved_output_tokens
    return ContextUsage(
        context_window=window,
        input_tokens=input_tokens,
        reserved_output_tokens=reserved_output_tokens,
        total_tokens=total,
        utilization=total / window,
        should_compact=total / window >= threshold,
        available_tokens=max(0, window - total),
    )
