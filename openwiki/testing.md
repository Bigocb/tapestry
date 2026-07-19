---
type: Reference
title: MEMIND Testing
description: Test strategy, fixtures, known limitations, and how to run tests for the MEMIND platform, including SQLite vs PostgreSQL compatibility notes.
tags: [memind, testing, pytest, sqlite, postgresql]
---

# Testing

MEMIND uses **pytest** with **pytest-asyncio** for async test support. Tests run against an in-memory SQLite database by default, which enables fast, isolated test runs without requiring a running PostgreSQL instance.

## Running Tests

```bash
# Run all tests
pytest -v

# Run specific test files
pytest tests/test_auth.py -v
pytest tests/test_memory_capture.py -v
pytest tests/test_pydantic_models.py -v

# Run database setup tests (requires PostgreSQL)
pytest tests/test_db_setup.py -v
```

## Test Configuration

[`pytest.ini`](../pytest.ini) configures:

- `asyncio_mode = auto` — all async tests are auto-detected
- `testpaths = tests`
- `pythonpath = .`

[`tests/conftest.py`](../tests/conftest.py) sets `DATABASE_URL` to `sqlite+aiosqlite:///:memory:` before any imports, overriding the default PostgreSQL connection.

## Test Files

| File | What it tests | Count |
|------|---------------|-------|
| [`test_fastapi_app.py`](../tests/test_fastapi_app.py) | App creation, health check, OpenAPI docs, CORS, 404 handling | ~6 tests |
| [`test_auth.py`](../tests/test_auth.py) | Registration, login, token refresh, protected routes, user isolation | ~20 tests |
| [`test_memory_capture.py`](../tests/test_memory_capture.py) | Memory capture CRUD, input validation, user isolation, state initialization | Multiple tests |
| [`test_pydantic_models.py`](../tests/test_pydantic_models.py) | Schema validation for all Pydantic models | Many tests |
| [`test_db_setup.py`](../tests/test_db_setup.py) | Database connection, pgvector extension, schema creation, embeddings | Postgres-only |

## SQLite vs PostgreSQL Compatibility

MEMIND's ORM uses custom type decorators ([`DBJSON`](../app/db/models.py) and [`GUID`](../app/db/models.py)) to handle differences between PostgreSQL and SQLite:

- **JSON/JSONB**: `DBJSON` uses `JSONB` on PostgreSQL, `JSON` on SQLite
- **UUID**: `GUID` uses native `UUID` on PostgreSQL, `String(36)` on SQLite

### Known PostgreSQL-Only Features

Some ORM features are PostgreSQL-specific and **will fail on SQLite**:

| Feature | Postgres Type | SQLite Fallback |
|---------|-------------|-----------------|
| Tag indexing | `GIN` index | Not supported |
| Vector similarity | `ivfflat` index on `vector` column | Not supported |
| `ARRAY` type | Native `ARRAY` | Not used in ORM (uses JSON instead) |
| `gen_random_uuid()` | Native function | Uses Python `uuid4()` |

The `test_db_setup.py` file tests PostgreSQL-specific features (pgvector, embeddings, GIN indexes) and requires a running PostgreSQL instance with pgvector enabled. These tests should be skipped or configured separately when running the main test suite against SQLite.

## Test Fixtures

Most test files create their own in-memory database fixtures:

```python
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture
async def test_db():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, ...)
    async with AsyncSessionLocal() as session:
        yield session
```

The `test_db` fixture creates fresh tables for each test session. Tests that need an authenticated user create a test user directly via the ORM and generate a JWT token via `create_access_token()`.

## Key Test Patterns

### Testing Authenticated Endpoints

```python
# Create user and get token
user = User(id=str(uuid4()), username="testuser", ...)
token = create_access_token(user_id=str(user.id), username=user.username)
headers = {"Authorization": f"Bearer {token}"}

# Make authenticated request
response = client.post("/api/memories/capture", json={...}, headers=headers)
```

### Testing Schema Validation

Pydantic model tests verify field constraints directly:

```python
with pytest.raises(ValidationError) as exc_info:
    UserCreate(username="ab", email="test@example.com", password="pass123")
assert "at least 3 characters" in str(exc_info.value)
```

## Dependencies

Key test dependencies from [`requirements.txt`](../requirements.txt):

- `pytest==7.4.3`
- `pytest-asyncio==0.21.1`
- `httpx==0.25.1` (for FastAPI `TestClient`)
- `aiosqlite` (implicit via SQLAlchemy async SQLite)

## What Is Not Tested

- Agent pipeline (not yet implemented)
- Voice transcription endpoint
- Search, story, timeline, and insights routes (not yet implemented)
- End-to-end integration tests with PostgreSQL
- Token expiration behavior in production