import re
from dataclasses import dataclass
from pathlib import Path

from datapilot.skills_engine.skill_registry import SkillInfo, discover_skills


WORD_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = frozenset(
    {
        "a", "an", "and", "are", "by", "for", "from", "how", "in", "into",
        "is", "of", "on", "or", "show", "the", "to", "using", "what",
        "which", "with", "write", "query", "sql", "data", "table", "tables",
    }
)


@dataclass(frozen=True, slots=True)
class SkillMatch:
    skill: SkillInfo
    score: int
    matched_terms: tuple[str, ...]


def _terms(value: str) -> set[str]:
    return {word for word in WORD_PATTERN.findall(value.lower()) if word not in STOP_WORDS}


def match_skills(
    user_query: str,
    skills_directory: Path,
    model_family: str,
    max_results: int = 5,
) -> list[SkillMatch]:
    if not isinstance(user_query, str) or not user_query.strip():
        raise ValueError("User query must be a nonempty string")
    if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results <= 0:
        raise ValueError("Maximum result count must be a positive integer")

    query_terms = _terms(user_query)
    if not query_terms:
        return []

    matches: list[SkillMatch] = []
    for skill in discover_skills(skills_directory, model_family):
        name_terms = _terms(skill.name.replace("_", " ").replace("-", " "))
        description_terms = _terms(skill.description)
        name_hits = query_terms & name_terms
        description_hits = query_terms & description_terms
        score = 3 * len(name_hits) + len(description_hits)
        if score:
            matches.append(
                SkillMatch(
                    skill=skill,
                    score=score,
                    matched_terms=tuple(sorted(name_hits | description_hits)),
                )
            )

    matches.sort(key=lambda match: (-match.score, match.skill.name, str(match.skill.path)))
    return matches[:max_results]
