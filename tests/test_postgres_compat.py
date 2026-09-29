"""Regression tests for SQLite-isms that break under PostgreSQL.

The suite runs on SQLite, which quietly tolerates two things Postgres does
not: unbounded-length assumptions on VARCHAR columns, and comparing a boolean
column against an integer. Both bugs lay dormant until the data and the app
moved onto Postgres, so these tests pin the fixes down.
"""

import re

from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.agents.embeddings import serialize_embedding
from app.db.models import Base, Memory
from app.main import MEMORIES_WITH_TIME_SIGNAL


class TestEmbeddingStorage:
    """The embedding column must stay unbounded."""

    def test_embedding_column_has_no_length_limit(self):
        # It was VARCHAR(3000). SQLite never enforced that, so the overflow
        # only appeared once the rows were inserted into Postgres.
        assert Memory.__table__.c.embedding.type.length is None

    def test_a_realistic_embedding_exceeds_the_old_limit(self):
        # Documents *why* the column must be unbounded.
        serialized = serialize_embedding([-0.02061180455166409] * 1024)
        assert len(serialized) > 3000


class TestReviewQueueSql:
    """The review-reconciliation SQL must bind its boolean."""

    def test_time_signal_clause_binds_the_boolean(self):
        statement = text(
            f"SELECT COUNT(*) FROM memories WHERE {MEMORIES_WITH_TIME_SIGNAL}"
        ).compile(dialect=postgresql.dialect())
        compiled = str(statement)

        assert "needs_review = %(queued)s" in compiled
        # `needs_review = 1` is the SQLite-ism that crashed startup.
        assert not re.search(r"needs_review\s*=\s*[01]\b", compiled)


class TestPostgresDdl:
    """Every table must be expressible in Postgres."""

    def test_every_table_compiles_for_postgres(self):
        for table in Base.metadata.sorted_tables:
            str(CreateTable(table).compile(dialect=postgresql.dialect()))
