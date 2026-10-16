from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from datapilot.memory.checkpoint_manager import checkpoint_config
from datapilot.memory.context_monitor import (
    COMPACTION_THRESHOLD,
    ContextUsage,
    assess_context,
    count_message_tokens,
)
from datapilot.memory.memory_compactor import (
    CompactionResult,
    MemoryTurn,
    Summarizer,
    compact_memory,
    save_compacted_summary,
)


@dataclass(frozen=True)
class PreparedMemory:
    messages: tuple[MemoryTurn, ...]
    usage: ContextUsage
    compaction: CompactionResult | None
    checkpoint: dict[str, dict[str, str]]


def prepare_memory_context(
    *,
    session_id: str,
    messages: Sequence[MemoryTurn],
    tokenizer: Callable[[str], Sequence[int]],
    summarizer: Summarizer,
    system_instructions: str,
    schema_knowledge: str = "",
    skill_instructions: str = "",
    previous_summary: str = "",
    artifact_references: Sequence[str] = (),
    context_window: int | None = None,
    reserved_output_tokens: int = 2048,
    preserve_recent: int = 6,
    tokens_per_message: int = 0,
    summary_path: Path | None = None,
) -> PreparedMemory:
    checkpoint = checkpoint_config(session_id)
    if not callable(tokenizer):
        raise TypeError("tokenizer must be callable")
    if not isinstance(system_instructions, str) or not system_instructions.strip():
        raise ValueError("system_instructions must be nonempty text")
    for value in (schema_knowledge, skill_instructions, previous_summary):
        if not isinstance(value, str):
            raise TypeError("Knowledge and summary must be text")
    if not isinstance(preserve_recent, int) or isinstance(preserve_recent, bool) or preserve_recent < 0:
        raise ValueError("preserve_recent must be a nonnegative integer")
    if any(not isinstance(turn, MemoryTurn) for turn in messages):
        raise TypeError("messages must contain MemoryTurn objects")
    if any(not isinstance(ref, str) or not ref.strip() for ref in artifact_references):
        raise ValueError("artifact_references must be nonempty strings")
    if len({turn.message_id for turn in messages}) != len(messages):
        raise ValueError("Message identifiers must be unique")
    if any(not turn.message_id.strip() or not turn.role.strip() for turn in messages):
        raise ValueError("Messages need identifiers and roles")

    def assemble(summary: str, turns: Sequence[MemoryTurn]) -> tuple[MemoryTurn, ...]:
        prefix = [MemoryTurn("__system__", "system", system_instructions)]
        if schema_knowledge.strip():
            prefix.append(MemoryTurn("__schema__", "system", "Verified schema:\n" + schema_knowledge))
        if skill_instructions.strip():
            prefix.append(MemoryTurn("__skills__", "system", "Selected skills:\n" + skill_instructions))
        if summary.strip():
            prefix.append(MemoryTurn("__summary__", "system", "Conversation summary:\n" + summary))
        if artifact_references:
            prefix.append(MemoryTurn("__artifacts__", "system", "Artifact references:\n" + "\n".join(artifact_references)))
        return (*prefix, *turns)

    def usage_for(turns: Sequence[MemoryTurn]) -> ContextUsage:
        count = count_message_tokens(
            [f"{turn.role}: {turn.content}" for turn in turns],
            tokenizer,
            tokens_per_message=tokens_per_message,
        )
        return assess_context(
            input_tokens=count,
            reserved_output_tokens=reserved_output_tokens,
            context_window=context_window,
            threshold=COMPACTION_THRESHOLD,
        )

    active = assemble(previous_summary, messages)
    usage = usage_for(active)
    compaction = None
    if usage.should_compact:
        compaction = compact_memory(
            messages,
            summarizer,
            previous_summary=previous_summary,
            preserve_recent=preserve_recent,
            artifact_references=artifact_references,
        )
        active = assemble(compaction.summary, compaction.recent_messages)
        usage = usage_for(active)
        if usage.should_compact:
            raise ValueError("Reconstructed context exceeds 85% budget; reduce recent messages or knowledge")
        if summary_path is not None and compaction.compacted_message_ids and compaction.summary.strip():
            save_compacted_summary(compaction, summary_path)
    return PreparedMemory(
        messages=tuple(active),
        usage=usage,
        compaction=compaction,
        checkpoint=checkpoint,
    )
