from typing import Any


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


TEXT = {"type": "string", "minLength": 1}
STRINGS = {"type": "array", "items": TEXT, "maxItems": 200}
DOCUMENTATION = _object(
    {
        "needed": {"type": "boolean"},
        "search_query": {"type": "string", "maxLength": 500},
        "reason": {**TEXT, "maxLength": 500},
    }
)
COMPLEXITY = _object({"level": {"enum": ["easy", "medium", "hard"]}, "reasoning": TEXT})
SQL_GENERATION = _object({"sql": TEXT, "explanation": TEXT, "assumptions": STRINGS})
SQL_REPAIR = _object({"sql": TEXT, "explanation": TEXT, "changes": STRINGS})
SQL_FALLBACK = _object(
    {
        "status": {"enum": ["ready", "needs_basic_knowledge", "unanswerable"]},
        "reason": TEXT,
        "sql": {"type": "string"},
        "explanation": {"type": "string"},
        "assumptions": STRINGS,
    }
)
PANDAS_PLAN = _object(
    {
        "operations": {**STRINGS, "minItems": 1, "maxItems": 20},
        "required_columns": STRINGS,
        "explanation": TEXT,
        "assumptions": STRINGS,
    }
)


def pandas_operations_schema(columns: list[str], max_operations: int) -> dict[str, Any]:
    names = {"type": "array", "items": {"enum": columns}, "minItems": 1, "maxItems": len(columns)}
    aggregations = {
        "type": "object",
        "minProperties": 1,
        "additionalProperties": False,
        "properties": {
            name: {"enum": ["sum", "mean", "min", "max", "count", "nunique"]} for name in columns
        },
    }
    parameters = {
        "select": {"columns": names},
        "filter": {
            "column": {"enum": columns},
            "operator": {
                "enum": ["eq", "ne", "gt", "gte", "lt", "lte", "in", "is_null", "not_null"]
            },
            "value": {
                "type": ["string", "number", "boolean", "null", "array"],
                "items": {"type": ["string", "number", "boolean", "null"]},
            },
        },
        "groupby": {"by": names, "aggregations": aggregations},
        "sort": {"by": names, "ascending": {"type": "boolean"}},
        "limit": {"rows": {"type": "integer", "minimum": 1, "maximum": 1000000}},
    }
    return _object(
        {
            "operations": {
                "type": "array",
                "minItems": 1,
                "maxItems": max_operations,
                "items": {
                    "oneOf": [
                        _object({"kind": {"const": kind}, "parameters": _object(props)})
                        for kind, props in parameters.items()
                    ]
                },
            }
        }
    )


VISUALIZATION = _object(
    {
        "chart_type": {"enum": ["bar", "line", "scatter", "histogram", "box", "pie"]},
        "library": {"enum": ["matplotlib", "seaborn", "plotly", "bokeh"]},
        "x": TEXT,
        "y": {"type": ["string", "null"]},
        "title": TEXT,
        "x_label": TEXT,
        "y_label": {"type": "string"},
        "reasoning": TEXT,
    }
)
