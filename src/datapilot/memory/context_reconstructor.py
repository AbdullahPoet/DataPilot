from collections.abc import Callable, Sequence
from dataclasses import dataclass

from datapilot.memory.context_monitor import ContextUsage, assess_context, count_message_tokens
from datapilot.memory.memory_compactor import CompactionResult, MemoryTurn


@dataclass(frozen=True)
class ReconstructedContext:
    messages: tuple[MemoryTurn, ...]
    usage: ContextUsage


def reconstruct_context(
    compacted: CompactionResult,
    tokenizer: Callable[[str], Sequence[int]],
    *,
    schema_knowledge: str = "",
    selected_skills: Sequence[str] = (),
    system_instructions: str = "",
    context_window: int | None = None,
    reserved_output_tokens: int = 2048,
    tokens_per_message: int = 0,
) -> ReconstructedContext:
    if not isinstance(compacted, CompactionResult):
        raise TypeError("compacted must be a CompactionResult")
    if not callable(tokenizer):
        raise TypeError("tokenizer must be callable")
    if any(not isinstance(value, str) for value in (schema_knowledge, system_instructions)):
        raise TypeError("Schema and system instructions must be strings")
    if any(not isinstance(skill, str) or not skill.strip() for skill in selected_skills):
        raise ValueError("Skills must be nonempty strings")

    sections = []
    if system_instructions.strip():
        sections.append(system_instructions.strip())
    if schema_knowledge.strip():
        sections.append(f"Verified schema:\n{schema_knowledge.strip()}")
    for index, skill in enumerate(selected_skills, start=1):
        sections.append(f"Selected skill {index}:\n{skill.strip()}")
    if compacted.summary.strip():
        sections.append(f"Compacted conversation memory:\n{compacted.summary.strip()}")
    if compacted.artifact_references:
        sections.append("Artifact references:\n" + "\n".join(compacted.artifact_references))

    messages = (
        (MemoryTurn(message_id="reconstructed_context", role="system", content="\n\n".join(sections)),)
        if sections
        else ()
    ) + compacted.recent_messages
    input_tokens = count_message_tokens(
        [message.content for message in messages],
        tokenizer,
        tokens_per_message=tokens_per_message,
    )
    usage = assess_context(
        input_tokens,
        reserved_output_tokens,
        context_window=context_window,
    )
    if usage.should_compact:
        raise ValueError(
            "Reconstructed context exceeds the 85% budget; reduce selected knowledge or compact further"
        )
    return ReconstructedContext(messages=messages, usage=usage)
