import re
from dataclasses import dataclass
from pathlib import Path

COMMON_LEVELS = ("easy", "medium", "hard")
MODEL_FAMILY_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")


@dataclass(frozen=True, slots=True)
class SkillInfo:
    name: str
    description: str
    category: str
    path: Path


def validate_model_family(model_family: str) -> str:
    if not isinstance(model_family, str):
        raise TypeError("Model family must be a string")
    normalized = model_family.strip().lower()
    if not MODEL_FAMILY_PATTERN.fullmatch(normalized):
        raise ValueError("Model family must use letters, digits, hyphens, or underscores")
    return normalized


def _read_metadata(path: Path) -> tuple[str, str]:
    content = path.read_text(encoding="utf-8-sig")
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"Skill is missing frontmatter: {path}")
    try:
        closing = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as error:
        raise ValueError(f"Skill frontmatter is not closed: {path}") from error
    fields: dict[str, str] = {}
    for line in lines[1:closing]:
        key, separator, value = line.partition(":")
        if separator and key.strip() in {"name", "description"}:
            fields[key.strip()] = value.strip().strip('"\'')
    name = fields.get("name", "")
    description = fields.get("description", "")
    if not name or not description:
        raise ValueError(f"Skill requires name and description: {path}")
    return name, description


def discover_skills(skills_directory: Path, model_family: str) -> list[SkillInfo]:
    family = validate_model_family(model_family)
    root = skills_directory.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Skills directory not found: {root}")
    categories = (*COMMON_LEVELS, "dialects", f"{family}_skills")
    skills: list[SkillInfo] = []
    for category in categories:
        directory = root / category
        if directory.is_symlink() or not directory.is_dir():
            continue
        paths = directory.glob("*.md") if category == "dialects" else directory.rglob("SKILL.md")
        for path in sorted(paths):
            if not path.is_file() or not path.resolve().is_relative_to(directory):
                continue
            name, description = _read_metadata(path)
            skills.append(SkillInfo(name, description, category, path))
    return skills
