from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from datapilot.skills_engine.skill_learning_manager import (
    LearnedSkill,
    SavedSkill,
    SkillVerification,
    save_verified_skill,
)
from datapilot.validation.result_verifier import (
    ExpectedResult,
    PandasResultLike,
    SQLResultLike,
    VerificationReport,
    verify_pandas_result,
    verify_sql_result,
)


@dataclass(frozen=True, slots=True)
class SkillLearningResult:
    saved_skill: SavedSkill
    verification: VerificationReport


def verify_and_save_skill(
    *,
    source_type: Literal["sql", "pandas"],
    result: SQLResultLike | PandasResultLike,
    expected_results: list[ExpectedResult],
    evidence_reference: str,
    skills_directory: Path,
    model_family: str,
    skill: LearnedSkill,
) -> SkillLearningResult:
    if source_type == "sql":
        if skill.dialect == "pandas":
            raise ValueError("SQL results cannot verify a Pandas skill")
        verification = verify_sql_result(result, expected_results, evidence_reference)
    elif source_type == "pandas":
        if skill.dialect != "pandas":
            raise ValueError("Pandas results cannot verify a SQL skill")
        verification = verify_pandas_result(result, expected_results, evidence_reference)
    else:
        raise ValueError("Unsupported analytical source type")

    if not verification.passed:
        failures = "; ".join(
            f"{item.case_id}: {item.reason}"
            for item in verification.evidence
            if item.status != "passed"
        )
        raise ValueError(f"Skill verification failed: {failures}")

    records = [
        SkillVerification(
            test_name=item.case_id,
            status="passed",
            evidence_reference=item.evidence_reference,
        )
        for item in verification.evidence
    ]
    saved = save_verified_skill(
        skills_directory=skills_directory,
        model_family=model_family,
        skill=skill,
        verifications=records,
    )
    return SkillLearningResult(saved_skill=saved, verification=verification)
