from hashlib import sha256
from pathlib import Path

from sqlalchemy.engine import Engine

from datapilot.knowledge.schema_inspector import inspect_schema
from datapilot.knowledge.schema_writer import write_schema_markdown


def schema_cache_path(engine: Engine, knowledge_directory: Path, schema: str | None = None) -> Path:
    url = engine.url.set(password=None)
    if url.get_backend_name() == "sqlite" and url.database not in (None, ":memory:"):
        database = str(Path(url.database).expanduser().resolve())
        url = url.set(database=database)
    identity = f"{url.render_as_string(hide_password=False)}|{schema or ''}"
    source_id = sha256(identity.encode("utf-8")).hexdigest()[:24]
    return knowledge_directory / "databases" / source_id / "schema.md"


def load_schema_knowledge(
    engine: Engine,
    knowledge_directory: Path,
    schema: str | None = None,
    refresh: bool = False,
) -> str:
    cache_path = schema_cache_path(engine, knowledge_directory, schema)
    if cache_path.is_file() and not refresh:
        return cache_path.read_text(encoding="utf-8")
    metadata = inspect_schema(engine, schema=schema)
    write_schema_markdown(metadata, cache_path)
    return cache_path.read_text(encoding="utf-8")
