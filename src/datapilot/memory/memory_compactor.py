from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemoryTurn:
    message_id: str
    role: str
    content: str


@dataclass(frozen=True)
class CompactionResult:
    summary: str
    recent_messages: tuple[MemoryTurn, ...]
    compacted_message_ids: tuple[str, ...]
    artifact_references: tuple[str, ...]


Summarizer = Callable[[str, Sequence[MemoryTurn]], str]


def compact_memory(
    messages: Sequence[MemoryTurn],
    summarize: Summarizer,
    *,
    previous_summary: str = "",
    preserve_recent: int = 6,
    artifact_references: Sequence[str] = (),
) -> CompactionResult:
    if isinstance(preserve_recent, bool) or not isinstance(preserve_recent, int) or preserve_recent < 0:
        raise ValueError("preserve_recent must be a nonnegative integer")
    if not callable(summarize):
        raise TypeError("summarize must be callable")
    if not isinstance(previous_summary, str):
        raise TypeError("previous_summary must be text")
    if any(not isinstance(reference, str) or not reference.strip() for reference in artifact_references):
        raise ValueError("Artifact references must be nonempty strings")
    if any(
        not isinstance(message, MemoryTurn)
        or not message.message_id.strip()
        or not message.role.strip()
        or not isinstance(message.content, str)
        for message in messages
    ):
        raise ValueError("Messages must have valid identifiers, roles, and content")
    identifiers = [message.message_id for message in messages]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Message identifiers must be unique")
    split = max(0, len(messages) - preserve_recent)
    older = tuple(messages[:split])
    recent = tuple(messages[split:])
    if not older:
        return CompactionResult(
            summary=previous_summary,
            recent_messages=recent,
            compacted_message_ids=(),
            artifact_references=tuple(artifact_references),
        )
    summary = summarize(previous_summary, older)
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Summarizer must return a nonempty text summary")
    return CompactionResult(
        summary=summary.strip(),
        recent_messages=recent,
        compacted_message_ids=tuple(message.message_id for message in older),
        artifact_references=tuple(artifact_references),
    )


def save_compacted_summary(result: CompactionResult, path: Path) -> Path:
    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path")
    if not result.summary.strip():
        raise ValueError("Cannot save an empty summary")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.summary + "\n", encoding="utf-8")
    return path
