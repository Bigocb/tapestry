"""One-off migration: copy every Tapestry row from SQLite into PostgreSQL.

The destination schema is created from the current ORM metadata, so it always
matches what the application expects. Rows are inserted through the very same
``Table`` objects the app uses, which means the ``GUID`` and ``DBJSON``
TypeDecorators translate SQLite strings/UUIDs and JSON into the native
Postgres ``uuid`` and ``jsonb`` types for us.

Tables are copied in foreign-key dependency order, and re-running the command
is safe: any table that already holds rows is skipped.

Usage (from the compose project root):

    docker compose run --rm \\
        -v "$PWD/memind.db:/legacy/memind.db:ro" \\
        -e SQLITE_PATH=/legacy/memind.db \\
        backend python -m scripts.migrate_sqlite_to_postgres
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import insert, select, text, update
from sqlalchemy.ext.asyncio import create_async_engine

# Importing the models module registers every table on ``Base.metadata``.
from app.db import models
from app.db.models import Base

DEFAULT_SQLITE_PATH = "./memind.db"


def _self_referential_columns(table) -> list[str]:
    """Columns whose foreign key points back at this same table.

    ``entities.parent_entity_id`` is one of these. Postgres checks foreign keys
    row by row, so a parent and its child cannot be inserted in the same batch.
    We insert these columns as NULL and patch them in a second pass.
    """

    return [
        fk.parent.name
        for fk in table.foreign_keys
        if fk.column.table is table
    ]


async def migrate(sqlite_path: str, database_url: str) -> int:
    sqlite_file = Path(sqlite_path)
    if not sqlite_file.is_file():
        print(f"error: SQLite database not found at {sqlite_file}", file=sys.stderr)
        return -1

    source = create_async_engine(f"sqlite+aiosqlite:///{sqlite_path}")
    target = create_async_engine(database_url)

    try:
        async with target.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        copied = 0
        async with source.connect() as src, target.begin() as dst:
            # sorted_tables is ordered so referenced tables come first.
            for table in Base.metadata.sorted_tables:
                existing = await dst.scalar(
                    text(f'SELECT COUNT(*) FROM "{table.name}"')
                )
                if existing:
                    print(f"  {table.name}: skipped ({existing} rows already present)")
                    continue

                rows = (await src.execute(select(table))).mappings().all()
                if not rows:
                    print(f"  {table.name}: empty")
                    continue

                deferred = _self_referential_columns(table)
                if deferred:
                    payload = [
                        {**dict(row), **{col: None for col in deferred}}
                        for row in rows
                    ]
                else:
                    payload = [dict(row) for row in rows]

                await dst.execute(insert(table), payload)

                if deferred:
                    key = list(table.primary_key.columns)[0]
                    patched = 0
                    for row in rows:
                        values = {c: row[c] for c in deferred if row[c] is not None}
                        if not values:
                            continue
                        await dst.execute(
                            update(table).where(key == row[key.name]).values(**values)
                        )
                        patched += 1
                    if patched:
                        print(f"  {table.name}: {patched} self-references patched")

                copied += len(rows)
                print(f"  {table.name}: {len(rows)} rows copied")

        return copied
    finally:
        await source.dispose()
        await target.dispose()


async def _main() -> int:
    sqlite_path = os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH)
    database_url = os.getenv("DATABASE_URL", "")

    if not database_url:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        return 1
    if not database_url.startswith("postgresql"):
        print(
            "error: refusing to migrate into a non-Postgres DATABASE_URL",
            file=sys.stderr,
        )
        return 1

    print(f"Migrating {sqlite_path} -> {database_url.rsplit('@', 1)[-1]}")
    copied = await migrate(sqlite_path, database_url)
    if copied < 0:
        return 1

    print(f"Done. {copied} rows copied." if copied else "Done. Nothing to copy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
