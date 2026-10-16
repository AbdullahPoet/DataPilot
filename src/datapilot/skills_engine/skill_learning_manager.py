import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from datapilot.skills_engine.skill_registry import validate_model_family


SLUG_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
EVIDENCE_STATUS = frozenset({"passed"})


@dataclass(frozen=True, slots=True)
class SkillVerification:
    test_name: str
    status: Literal["passed", "failed"]
    evidence_reference: str


@dataclass(frozen=True, slots=True)
class LearnedSkill:
    name: str
    description: str
    technique: str
    applicability: str
    example: str
    limitations: str
    dialect: Literal["sqlite", "postgresql", "mysql", "pandas"]


@dataclass(frozen=True, slots=True)
class SavedSkill:
    path: Path
    model_family: str
    verification_count: int


def _validated_text(value: str, field: str, max_length: int = 12000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    text = value.strip()
    if len(text) > max_length or "\x00" in text:
        raise ValueError(f"{field} has an invalid length or contains null bytes")
    return text


def _validate_skill(skill: LearnedSkill) -> None:
    if not SLUG_PATTERN.fullmatch(skill.name):
        raise ValueError("Skill name must be a lowercase hyphenated slug")
    _validated_text(skill.description, "Description", 250)
    _validated_text(skill.technique, "Technique")
    _validated_text(skill.applicability, "Applicability", 2000)
    _validated_text(skill.example, "Example")
    _validated_text(skill.limitations, "Limitations", 2000)
    if skill.dialect not in {"sqlite", "postgresql", "mysql", "pandas"}:
        raise ValueError("Unsupported skill dialect")


def _validate_verifications(verifications: list[SkillVerification]) -> None:
    if not verifications:
        raise ValueError("At least one independent verification is required")
    names: set[str] = set()
    for verification in verifications:
        name = _validated_text(verification.test_name, "Verification name", 150)
        _validated_text(verification.evidence_reference, "Evidence reference", 500)
        if verification.status not in EVIDENCE_STATUS:
            raise ValueError("All verifications must have passed")
        if name in names:
            raise ValueError("Verification names must be unique")
        names.add(name)


def _markdown(skill: LearnedSkill, verifications: list[SkillVerification]) -> str:
    description = skill.description.strip().replace("\n", " ").replace("\r", " ")
    summary = [
        "---",
        f"name: {skill.name}",
        f"description: {json.dumps(description, ensure_ascii=False)}",
        "---",
        "",
        f"# {skill.name}",
        "",
        f"Dialect: {skill.dialect}",
        "",
        "## When to use",
        "",
        skill.applicability.strip(),
        "",
        "## Reusable technique",
        "",
        skill.technique.strip(),
        "",
        "## Example",
        "",
        skill.example.strip(),
        "",
        "## Limitations",
        "",
        skill.limitations.strip(),
        "",
        "## Verification evidence",
        "",
    ]
    for verification in verifications:
        summary.append(f"- {verification.test_name.strip()}: passed ({verification.evidence_reference.strip()})")
    summary.extend(["", f"Verified at: {datetime.now(timezone.utc).isoformat()}", ""])
    return "\n".join(summary)


def save_verified_skill(
    skills_directory: Path,
    model_family: str,
    skill: LearnedSkill,
    verifications: list[SkillVerification],
) -> SavedSkill:
    family = validate_model_family(model_family)
    _validate_skill(skill)
    _validate_verifications(verifications)
    root = Path(skills_directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination_directory = root / f"{family}_skills" / skill.name
    if destination_directory.is_symlink():
        raise ValueError("Skill destination must not be a symbolic link")
    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = destination_directory / "SKILL.md"
    if not destination_directory.resolve().is_relative_to(root):
        raise ValueError("Skill destination escapes the skills directory")
    content = _markdown(skill, verifications)
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError as error:
        raise FileExistsError(f"Skill already exists: {skill.name}") from error
    return SavedSkill(path=destination, model_family=family, verification_count=len(verifications))
