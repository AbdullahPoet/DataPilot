from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from datapilot.skills_engine.complexity_classifier import (
    ComplexityAssessment,
    classify_query_complexity,
)
from datapilot.skills_engine.skill_loader import load_selected_skills
from datapilot.skills_engine.skill_matcher import SkillMatch, match_skills
from datapilot.skills_engine.skill_registry import discover_skills, validate_model_family


SourceType = Literal["sql", "csv", "xlsx"]


@dataclass(frozen=True, slots=True)
class SkillSelection:
    assessment: ComplexityAssessment
    selected: tuple[SkillMatch, ...]
    instructions: str

    @property
    def skill_names(self) -> tuple[str, ...]:
        return tuple(match.skill.name for match in self.selected)


def orchestrate_skills(
    user_query: str,
    model_configuration: Mapping[str, str | int],
    skills_directory: Path,
    model_family: str,
    *,
    source_type: SourceType = "sql",
    source_context: str = "",
    max_skills: int = 3,
    max_skill_characters: int = 30000,
    timeout: float = 60.0,
) -> SkillSelection:
    if isinstance(max_skills, bool) or not isinstance(max_skills, int) or max_skills <= 0:
        raise ValueError("Maximum skill count must be a positive integer")
    if isinstance(max_skill_characters, bool) or not isinstance(max_skill_characters, int) or max_skill_characters <= 0:
        raise ValueError("Maximum skill content length must be a positive integer")
    family = validate_model_family(model_family)
    available = discover_skills(skills_directory, family)
    assessment = classify_query_complexity(
        user_query,
        model_configuration,
        source_type=source_type,
        source_context=source_context,
        timeout=timeout,
    )
    ranked = match_skills(
        user_query=user_query,
        skills_directory=skills_directory,
        model_family=family,
        max_results=max(1, len(available)),
    )
    allowed_categories = {assessment.level, "dialects", f"{family}_skills"}
    eligible = [match for match in ranked if match.skill.category in allowed_categories]
    unique_names: set[str] = set()
    selected: list[SkillMatch] = []
    for match in eligible:
        if match.skill.name in unique_names:
            continue
        if sum(skill.name == match.skill.name for skill in available) != 1:
            continue
        unique_names.add(match.skill.name)
        selected.append(match)
        if len(selected) == max_skills:
            break
    instructions = load_selected_skills(
        skills_directory=skills_directory,
        model_family=family,
        selected_names=[match.skill.name for match in selected],
        max_characters=max_skill_characters,
    )
    return SkillSelection(
        assessment=assessment,
        selected=tuple(selected),
        instructions=instructions,
    )
