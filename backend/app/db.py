"""SQLite engine + session management (SQLModel)."""

import json
import logging
from collections.abc import Generator

from pydantic_core import PydanticUndefined
from sqlalchemy import types as sa_types
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

logger = logging.getLogger(__name__)

# Ensure the data dir exists before SQLite tries to create the file there.
settings.data_path.mkdir(parents=True, exist_ok=True)

_DB_PATH = settings.data_path / "app.db"
engine = create_engine(
    f"sqlite:///{_DB_PATH}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """Create all tables, then additively sync any missing columns. Called on startup."""
    # Import models so their tables register on SQLModel.metadata.
    import app.models  # noqa: F401

    # create_all only creates MISSING TABLES; it never ADDs columns to an existing
    # table. So whenever a phase adds a column to an existing model, a pre-existing
    # app.db would 500 with "no such column" on the next SELECT. The additive sync
    # below closes that gap for the (SQLite) real DB.
    SQLModel.metadata.create_all(engine)
    _sync_additive_columns()


def _sqlite_affinity(sa_type: object) -> str:
    """Map a SQLAlchemy column type to a SQLite column affinity keyword.

    Only the coarse affinities matter for ``ALTER TABLE ADD COLUMN``; SQLite is
    dynamically typed, so anything unrecognized falls back to ``TEXT`` (JSON, String,
    Text, DateTime, Enum, ... all store as TEXT here).
    """
    # Boolean is NOT a subclass of Integer in SQLAlchemy — check it first.
    if isinstance(sa_type, sa_types.Boolean):
        return "INTEGER"
    if isinstance(sa_type, sa_types.Integer):
        return "INTEGER"
    if isinstance(sa_type, (sa_types.Float, sa_types.Numeric)):
        return "REAL"
    return "TEXT"


def _default_clause(column: object, model_field: object) -> str:
    """Derive a `` DEFAULT ...`` clause (incl. leading space) for a new column, or ``""``.

    Rules (additive & safe — only literal, constant defaults):
    - JSON list/dict columns get ``DEFAULT '[]'`` / ``DEFAULT '{}'`` so legacy rows read
      back a valid container (a NULL would arrive as ``None`` and could break callers /
      Pydantic). JSON columns without a container factory (e.g. nullable ``object``
      values) stay NULL.
    - Scalar columns with a simple literal python default (str/int/bool/float) emit that
      literal. Columns whose default comes from a ``default_factory`` that isn't a
      list/dict (e.g. ``datetime`` via ``_utcnow``) are left NULL — a runtime factory is
      not a constant SQL default.
    """
    if model_field is None:
        return ""

    factory = getattr(model_field, "default_factory", None)

    # JSON columns: seed a valid empty container so a legacy NULL never surfaces.
    if isinstance(column.type, sa_types.JSON):
        if factory is not None:
            try:
                value = factory()
            except Exception:  # noqa: BLE001 — a non-trivial factory just means "no default"
                value = None
            if isinstance(value, (list, dict)):
                return f" DEFAULT '{json.dumps(value)}'"
        return ""

    # Non-JSON: only a literal (non-factory) constant default becomes a SQL default.
    if factory is not None:
        return ""
    default = getattr(model_field, "default", PydanticUndefined)
    if default is PydanticUndefined or default is None:
        return ""
    if isinstance(default, bool):
        return f" DEFAULT {1 if default else 0}"
    if isinstance(default, (int, float)):
        return f" DEFAULT {default}"
    if isinstance(default, str):
        escaped = default.replace("'", "''")
        return f" DEFAULT '{escaped}'"
    return ""


def _sync_additive_columns() -> None:
    """ADD any column present in a SQLModel table but missing from the live SQLite table.

    Generic, idempotent, and additive-only: it never drops, renames, or alters existing
    columns. Each ALTER is isolated so one hiccup never crashes startup.
    """
    # Map each live table name to its SQLModel class so we can read Pydantic field
    # defaults (used to derive constant SQL defaults for the added columns). SQLModel's
    # Pydantic metaclass shadows ``.registry``, so reach the ORM registry via a mapped
    # class's real ``__mapper__`` instead.
    import app.models as _models

    table_to_model: dict[str, object] = {}
    for obj in vars(_models).values():
        mapper = getattr(obj, "__mapper__", None) if isinstance(obj, type) else None
        if mapper is None:
            continue
        for m in mapper.registry.mappers:
            local_table = getattr(m, "local_table", None)
            if local_table is not None:
                table_to_model[local_table.name] = m.class_
        break

    with engine.begin() as conn:
        for table in SQLModel.metadata.tables.values():
            try:
                rows = conn.exec_driver_sql(
                    f'PRAGMA table_info("{table.name}")'
                ).fetchall()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Column sync: cannot inspect table %s: %s", table.name, exc)
                continue
            if not rows:
                # Table doesn't exist yet (create_all should have made it) — skip.
                continue
            existing = {row[1] for row in rows}  # row[1] = column name

            model = table_to_model.get(table.name)
            model_fields = getattr(model, "model_fields", {}) if model is not None else {}

            for column in table.columns:
                if column.name in existing:
                    continue
                affinity = _sqlite_affinity(column.type)
                default_sql = _default_clause(column, model_fields.get(column.name))
                ddl = (
                    f'ALTER TABLE "{table.name}" '
                    f'ADD COLUMN "{column.name}" {affinity}{default_sql}'
                )
                try:
                    conn.exec_driver_sql(ddl)
                    logger.info("Column sync: added %s.%s", table.name, column.name)
                except Exception as exc:  # noqa: BLE001 — never crash startup on a hiccup
                    logger.warning(
                        "Column sync: failed to add %s.%s: %s",
                        table.name,
                        column.name,
                        exc,
                    )


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a DB session."""
    with Session(engine) as session:
        yield session
