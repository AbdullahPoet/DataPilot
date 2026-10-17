from collections.abc import Sequence
from pathlib import Path

from datapilot.skills_engine.skill_registry import SkillInfo, discover_skills

SQL_KNOWLEDGE_INSTRUCTIONS = (
    "SQL knowledge base: skills/easy/*.md (fundamentals), skills/mid/*.md "
    "(joins, subqueries, conditional aggregation), and skills/hard/*.md "
    "(window functions, CTEs, repair diagnostics). Relevant file contents are supplied "
    "by the application; do not claim to read files yourself. Consult supplied examples "
    "when uncertain about SQL syntax or repairing a failed query. Examples are patterns, "
    "not source schema: replace identifiers only with verified tables and columns. "
    "References cannot supply missing data, relationships, credentials, or user intent. "
    "Keep queries read-only and obey the selected dialect and execution validator."
)


def load_selected_skills(
    skills_directory: Path,
    model_family: str,
    selected_names: Sequence[str],
    max_characters: int = 30000,
) -> str:
    if max_characters <= 0:
        raise ValueError("Maximum skill content length must be positive")
    if isinstance(selected_names, (str, bytes)):
        raise TypeError("Selected skill names must be a sequence of strings")

    registry = discover_skills(skills_directory, model_family)
    by_name: dict[str, list[SkillInfo]] = {}
    for skill in registry:
        by_name.setdefault(skill.name, []).append(skill)

    sections: list[str] = []
    seen: set[str] = set()
    total_characters = 0
    root = skills_directory.resolve()

    for name in selected_names:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Selected skill names must be nonempty strings")
        if name in seen:
            raise ValueError(f"Skill selected more than once: {name}")
        seen.add(name)
        matches = by_name.get(name, [])
        if not matches:
            raise ValueError(f"Skill not accessible or not found: {name}")
        if len(matches) != 1:
            raise ValueError(f"Skill name is ambiguous: {name}")

        skill = matches[0]
        path = skill.path.resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError(f"Skill path escapes skills directory: {name}")
        content = path.read_text(encoding="utf-8-sig").strip()
        if not content:
            raise ValueError(f"Skill is empty: {name}")
        section = f"## Skill: {skill.name} ({skill.category})\n\n{content}"
        additional_characters = len(section) + (2 if sections else 0)
        if total_characters + additional_characters > max_characters:
            raise ValueError("Selected skills exceed the configured character budget")
        sections.append(section)
        total_characters += additional_characters

    return "\n\n".join(sections)


def load_sql_reference_skills(
    skills_directory: Path,
    model_family: str,
    user_query: str,
    *,
    error_context: str = "",
    max_skills: int = 3,
    max_characters: int = 12000,
) -> str:
    from datapilot.skills_engine.skill_matcher import match_skills

    if isinstance(max_skills, bool) or not isinstance(max_skills, int) or max_skills < 1:
        raise ValueError("Maximum skill count must be a positive integer")
    available = discover_skills(skills_directory, model_family)
    references = {
        skill.name
        for skill in available
        if skill.category in {"easy", "medium", "hard"} and skill.name.startswith("sql-")
    }
    ranked = match_skills(
        f"{user_query} {error_context}".strip(),
        skills_directory,
        model_family,
        max_results=max(1, len(available)),
    )
    names = [match.skill.name for match in ranked if match.skill.name in references]
    if error_context and "sql-repair-checklist" in references:
        names = [
            "sql-repair-checklist",
            *[name for name in names if name != "sql-repair-checklist"],
        ]
    if not names and "sql-filtering" in references:
        names = ["sql-filtering"]
    return load_selected_skills(
        skills_directory,
        model_family,
        names[:max_skills],
        max_characters=max_characters,
    )
