"""The migrations, verified without a database server.

``alembic upgrade head --sql`` really executes the migration scripts; it just
emits DDL instead of sending it. That is enough to prove three things that
otherwise only surface the first time someone runs a migration for real:

* the migration chain is well-formed and runs from zero;
* it produces exactly the schema the SQLAlchemy models describe, constraint
  names included — so the models and the migrations cannot drift apart;
* every table it creates can be dropped again.
"""

from __future__ import annotations

import contextlib
import io
import re

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.config import BACKEND_DIR
from app.db.base import Base

ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


@pytest.fixture(scope="module")
def rendered_sql() -> str:
    """The DDL for the whole chain, rendered offline."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        command.upgrade(alembic_config(), "head", sql=True)
    return buffer.getvalue()


def _statements(sql: str) -> list[str]:
    out = []
    for chunk in sql.split(";"):
        body = "\n".join(line for line in chunk.splitlines() if not line.strip().startswith("--"))
        normalized = " ".join(body.split())
        if normalized.upper().startswith(("CREATE TABLE", "CREATE INDEX")):
            out.append(normalized)
    return out


def _object_name(statement: str) -> str:
    match = re.match(r"CREATE (?:TABLE|INDEX) (\w+)", statement)
    assert match, statement
    return match.group(1)


def _clauses(create_table: str) -> frozenset[str]:
    """Split a CREATE TABLE body into top-level clauses.

    Comparing sets rather than strings makes the assertion independent of the
    order SQLAlchemy happens to emit columns and constraints in.
    """
    body = create_table[create_table.index("(") + 1 : create_table.rindex(")")]
    depth, current, parts = 0, "", []
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    parts.append(current.strip())
    return frozenset(part for part in parts if part)


def _metadata_statements() -> dict[str, str]:
    dialect = postgresql.dialect()
    out: dict[str, str] = {}
    for table in Base.metadata.tables.values():
        out[table.name] = " ".join(str(CreateTable(table).compile(dialect=dialect)).split())
        for index in table.indexes:
            assert index.name
            out[index.name] = " ".join(str(CreateIndex(index).compile(dialect=dialect)).split())
    return out


# --------------------------------------------------------------------------


def test_migration_chain_is_linear_and_starts_from_nothing() -> None:
    script = ScriptDirectory.from_config(alembic_config())
    revisions = list(script.walk_revisions())

    assert [rev.revision for rev in revisions] == ["0003", "0002", "0001"]
    assert revisions[-1].down_revision is None
    assert len(script.get_heads()) == 1, "a branched history would make `head` ambiguous"


def test_upgrade_from_zero_renders_the_whole_schema(rendered_sql: str) -> None:
    """M1 exit criterion: a fresh database can be created from migrations."""
    created = {_object_name(s) for s in _statements(rendered_sql) if s.startswith("CREATE TABLE")}
    created.discard("alembic_version")

    assert created == set(Base.metadata.tables)


def test_migrations_produce_exactly_the_schema_the_models_describe(rendered_sql: str) -> None:
    """The anti-drift test.

    Constraint names are compared too, so a model change that is not mirrored in
    a migration fails here rather than in production.
    """
    migration = {_object_name(s): s for s in _statements(rendered_sql)}
    migration.pop("alembic_version", None)
    metadata = _metadata_statements()

    assert set(migration) == set(metadata)

    differences: list[str] = []
    for name in sorted(migration):
        produced, expected = migration[name], metadata[name]
        if produced.startswith("CREATE INDEX"):
            if produced != expected:
                differences.append(f"{name}\n  migration: {produced}\n  models:    {expected}")
            continue
        only_migration = _clauses(produced) - _clauses(expected)
        only_models = _clauses(expected) - _clauses(produced)
        if only_migration or only_models:
            differences.append(
                f"{name}\n  only in migration: {sorted(only_migration)}"
                f"\n  only in models:    {sorted(only_models)}"
            )

    assert not differences, "migrations and models disagree:\n\n" + "\n\n".join(differences)


def test_catalog_tables_are_created_before_the_tables_that_reference_them(
    rendered_sql: str,
) -> None:
    order = [_object_name(s) for s in _statements(rendered_sql) if s.startswith("CREATE TABLE")]
    position = {name: i for i, name in enumerate(order)}

    for child, parent in (
        ("categories", "merchants"),
        ("products", "categories"),
        ("product_variants", "products"),
        ("inventory", "product_variants"),
        ("compatibility_rules", "products"),
        ("product_relationships", "products"),
    ):
        assert position[parent] < position[child], f"{child} is created before {parent}"


def test_downgrade_drops_every_table_it_created() -> None:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        # Offline downgrade needs an explicit range: there is no database
        # to ask where the schema currently is.
        command.downgrade(alembic_config(), "head:base", sql=True)
    sql = buffer.getvalue()

    dropped = set(re.findall(r"DROP TABLE (\w+)", sql))
    assert set(Base.metadata.tables) <= dropped


def test_the_specified_seven_tables_are_isolated_in_the_first_migration(
    rendered_sql: str,
) -> None:
    """ADR-003.

    Migration 0001 is exactly the schema architecture.md specifies. The
    compatibility_targets table, which the specification does not define, is
    added by 0002 so that the specified schema can be reviewed on its own.
    """
    head, _, tail = rendered_sql.partition("Running upgrade 0001 -> 0002")

    assert "CREATE TABLE compatibility_targets" not in head
    assert "CREATE TABLE compatibility_targets" in tail
    for specified in (
        "merchants",
        "categories",
        "products",
        "product_variants",
        "inventory",
        "compatibility_rules",
        "product_relationships",
    ):
        assert f"CREATE TABLE {specified}" in head
