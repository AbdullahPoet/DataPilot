from collections.abc import Sequence
from pathlib import Path

from datapilot.skills_engine.skill_registry import SkillInfo, discover_skills


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
