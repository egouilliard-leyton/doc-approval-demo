"""Additive-column auto-migration tests (app.db.init_db).

Hermetic/offline: each test builds a throwaway SQLite file, simulates an *old* DB by
recreating a table WITHOUT some of the model's columns, then asserts init_db() adds the
missing columns back (with sensible defaults) and the model reads cleanly afterwards.
"""

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

import app.db as db
from app.models import DocTypeDefinitionRow


def _columns(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall()
    return {row[1] for row in rows}


def test_init_db_adds_missing_columns(tmp_path: Path, monkeypatch):
    """A table missing several model columns gets them back on init_db()."""
    test_engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    monkeypatch.setattr(db, "engine", test_engine)

    # Simulate a legacy DB: a doctypedefinitionrow table missing four columns the model
    # now declares — icon (str default), version (int default), preferred_ocr_engine
    # (nullable str), ocr_fallback_engines (JSON list default).
    with test_engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE doctypedefinitionrow (
                name VARCHAR PRIMARY KEY,
                label VARCHAR,
                extraction_definition JSON,
                rule_definition JSON,
                citation_paths JSON,
                builtin BOOLEAN,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO doctypedefinitionrow
                (name, label, extraction_definition, rule_definition, citation_paths,
                 builtin, created_at, updated_at)
            VALUES
                ('legacy', 'Legacy', '{}', '{}', '[]', 0,
                 '2020-01-01 00:00:00', '2020-01-01 00:00:00')
            """
        )

    before = _columns(test_engine, "doctypedefinitionrow")
    assert "preferred_ocr_engine" not in before
    assert "ocr_fallback_engines" not in before
    assert "version" not in before

    db.init_db()

    after = _columns(test_engine, "doctypedefinitionrow")
    for col in ("icon", "version", "preferred_ocr_engine", "ocr_fallback_engines"):
        assert col in after, f"expected {col} to be added, got {sorted(after)}"

    # The legacy row now reads cleanly through the model (no "no such column" 500).
    with Session(test_engine) as session:
        row = session.get(DocTypeDefinitionRow, "legacy")
        assert row is not None
        assert row.preferred_ocr_engine is None       # nullable str, no default -> NULL
        assert row.ocr_fallback_engines == []          # JSON list default '[]', not None
        assert row.version == 1                         # int literal default
        assert row.icon == ""                           # str literal default


def test_init_db_is_idempotent(tmp_path: Path, monkeypatch):
    """Running init_db twice on the same DB is a no-op the second time (no errors)."""
    test_engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setattr(db, "engine", test_engine)

    db.init_db()
    first = _columns(test_engine, "doctypedefinitionrow")
    # Fresh create_all already has every model column, so the sync must add nothing.
    assert "preferred_ocr_engine" in first
    assert "ocr_fallback_engines" in first

    db.init_db()  # second pass must not raise or duplicate columns
    second = _columns(test_engine, "doctypedefinitionrow")
    assert first == second


def test_sync_adds_columns_to_every_table(tmp_path: Path, monkeypatch):
    """After create_all + sync, each model table matches its model's declared columns."""
    test_engine = create_engine(f"sqlite:///{tmp_path / 'all.db'}")
    monkeypatch.setattr(db, "engine", test_engine)

    db.init_db()

    for table in SQLModel.metadata.tables.values():
        live = _columns(test_engine, table.name)
        declared = {c.name for c in table.columns}
        assert declared <= live, f"{table.name} missing {declared - live}"
