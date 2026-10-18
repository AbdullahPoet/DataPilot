import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from datapilot.ingestion.data_profiler import profile_dataframe
from datapilot.ingestion.file_loader import load_data_file
from datapilot.knowledge.file_knowledge_writer import format_file_knowledge


@dataclass(frozen=True, slots=True)
class JoinedSource:
    dataframe: pd.DataFrame
    source_id: str
    knowledge: str
    evidence: dict[str, Any]


def join_frames(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    left_on: str,
    right_on: str,
    how: str = "left",
    relationship: str = "many_to_one",
    max_rows: int = 1_000_000,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if how not in {"left", "inner"}:
        raise ValueError("Join type must be left or inner")
    if relationship not in {"one_to_one", "one_to_many", "many_to_one", "many_to_many"}:
        raise ValueError("Invalid join relationship")
    if type(max_rows) is not int or max_rows < 1:
        raise ValueError("Join row limit must be positive")
    if max(len(left), len(right)) > max_rows:
        raise ValueError("Join input exceeds the row limit")
    if left_on not in left or right_on not in right:
        raise ValueError("Join keys must reference existing columns")
    if not left.columns.is_unique or not right.columns.is_unique or set(left) & set(right):
        raise ValueError("Join columns must be unique and qualified by source alias")
    left_key, right_key = left[left_on], right[right_on]
    left_valid = left_key.dropna()
    right_valid = right_key.dropna()
    if relationship in {"one_to_one", "one_to_many"} and left_valid.duplicated().any():
        raise ValueError("Left key is not unique for the selected relationship")
    if relationship in {"one_to_one", "many_to_one"} and right_valid.duplicated().any():
        raise ValueError("Right key is not unique for the selected relationship")
    left_counts = left_valid.value_counts().rename("left_count").to_frame()
    right_counts = right_valid.value_counts().rename("right_count").to_frame()
    counts = left_counts.join(right_counts, how="left").fillna(0)
    projected = sum(
        int(a) * (max(1, int(b)) if how == "left" else int(b))
        for a, b in counts.itertuples(index=False, name=None)
    ) + (int(left_key.isna().sum()) if how == "left" else 0)
    if projected > max_rows:
        raise ValueError("Join output would exceed the row limit; narrow the keys or inputs")
    merged = left.merge(
        right.loc[right_key.notna()],
        left_on=left_on,
        right_on=right_on,
        how=how,
        sort=False,
    )
    diagnostics = {
        "left_on": left_on,
        "right_on": right_on,
        "how": how,
        "relationship": relationship,
        "left_rows": len(left),
        "right_rows": len(right),
        "left_duplicate_keys": int(left_valid.duplicated().sum()),
        "right_duplicate_keys": int(right_valid.duplicated().sum()),
        "unmatched_left_rows": int((~left_key.isin(right_valid) | left_key.isna()).sum()),
        "unmatched_right_rows": int((~right_key.isin(left_valid) | right_key.isna()).sum()),
        "output_rows": len(merged),
        "null_keys_match": False,
    }
    return merged, diagnostics


def load_joined_source(configuration: Mapping[str, Any]) -> JoinedSource:
    sources = configuration.get("files")
    joins = configuration.get("joins")
    if not isinstance(sources, list) or not 2 <= len(sources) <= 8:
        raise ValueError("Select between two and eight files")
    if not isinstance(joins, list) or len(joins) != len(sources) - 1:
        raise ValueError("Each additional file requires one join")
    frames: dict[str, pd.DataFrame] = {}
    manifest = []
    for source in sources:
        alias = source.get("alias")
        if not isinstance(alias, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", alias):
            raise ValueError("Source aliases must be short identifiers")
        if alias in frames:
            raise ValueError("Source aliases must be unique")
        path = Path(source["path"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        frame = load_data_file(path, sheet_name=source.get("sheet_name"))
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Source changed while loading; reload the files")
        if len(frame) > 1_000_000:
            raise ValueError("File exceeds the input row limit")
        if not frame.columns.is_unique or any(not isinstance(c, str) or not c for c in frame):
            raise ValueError("Source columns must be unique non-empty strings")
        frames[alias] = frame.add_prefix(alias + ".")
        manifest.append(
            {
                "alias": alias,
                "file_name": path.name,
                "sha256": digest,
                "sheet_name": source.get("sheet_name"),
                "rows": len(frame),
            }
        )
    aliases = list(frames)
    frame = frames[aliases[0]]
    diagnostics = []
    for alias, spec in zip(aliases[1:], joins, strict=True):
        if spec.get("right_alias") != alias:
            raise ValueError("Joins must follow the selected file order")
        frame, details = join_frames(
            frame,
            frames[alias],
            left_on=spec["left_on"],
            right_on=spec["right_on"],
            how=spec.get("how", "left"),
            relationship=spec.get("relationship", "many_to_one"),
        )
        diagnostics.append(details)
    evidence = {"files": manifest, "joins": diagnostics, "input_rows": len(frame)}
    identity = json.dumps({"files": manifest, "joins": joins}, sort_keys=True)
    return JoinedSource(
        frame,
        hashlib.sha256(identity.encode()).hexdigest(),
        format_file_knowledge(profile_dataframe(frame)),
        evidence,
    )
