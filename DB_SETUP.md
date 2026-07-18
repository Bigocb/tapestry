# Database Setup - MEMIND

## Phase 1, Issue 1: Postgres with pgvector on Render

### Manual Setup on Render

1. **Create PostgreSQL Database on Render:**
   - Go to https://dashboard.render.com
   - Click "Create +" → "PostgreSQL"
   - Name: `memind-db`
   - Database: `memind`
   - User: `memind_user` (or your choice)
   - Region: Choose closest to you (default: Oregon)
   - Pricing Plan: Free (or Starter for production)
   - Click "Create Database"

2. **Wait for database to be ready** (~1-2 minutes)

3. **Copy the connection string** from the Render dashboard and save as `DATABASE_URL` environment variable

### Enable pgvector Extension

Once the database is created, you need to enable the pgvector extension:

```bash
# Install psql CLI tool if you don't have it:
# macOS: brew install postgresql
# Ubuntu/Debian: sudo apt-get install postgresql-client
# Windows: Download from https://www.postgresql.org/download/windows/

# Connect to your Render Postgres database:
psql <DATABASE_URL>

# Enable pgvector extension:
CREATE EXTENSION IF NOT EXISTS vector;

# Verify it's installed:
SELECT * FROM pg_extension WHERE extname='vector';

# Exit:
\q
```

### Local Development Setup

1. **Install PostgreSQL locally:**
   - macOS: `brew install postgresql`
   - Ubuntu/Debian: `sudo apt-get install postgresql postgresql-contrib`
   - Windows: Download from https://www.postgresql.org/download/windows/

2. **Start PostgreSQL:**
   ```bash
   # macOS/Linux
   brew services start postgresql
   
   # Or manually:
   postgres -D /usr/local/var/postgres
   ```

3. **Create local database:**
   ```bash
   createdb memind
   ```

4. **Connect and enable pgvector:**
   ```bash
   psql memind
   CREATE EXTENSION IF NOT EXISTS vector;
   \q
   ```

5. **Set .env for local development:**
   ```bash
   DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/memind
   ```

### Run Tests

```bash
# Install dependencies
pip install -r requirements.txt

# Run database tests
pytest tests/test_db_setup.py -v

# Run all tests
pytest -v
```

### Expected Test Output

```
tests/test_db_setup.py::test_database_connection PASSED
tests/test_db_setup.py::test_pgvector_extension_installed PASSED
tests/test_db_setup.py::test_schema_created PASSED
tests/test_db_setup.py::test_can_insert_user PASSED
tests/test_db_setup.py::test_can_insert_memory_with_embedding PASSED
tests/test_db_setup.py::test_can_query_embeddings PASSED
tests/test_db_setup.py::test_user_isolation PASSED
```

### Schema Overview

Tables created automatically via SQLAlchemy `Base.metadata.create_all()`:

- **users** - User accounts with auth
- **memories** - Core memory storage with processing states
- **entities** - Extracted entities (people, places, events, etc.)
- **stories** - Generated narratives from memories
- **job_status** - Async job tracking

See `app/db/models.py` for full schema definition.

### Troubleshooting

**"pgvector extension not found":**
- Ensure PostgreSQL version is 13+
- On Render, pgvector should be pre-installed; if not, open a support ticket

**"Connection refused":**
- Check DATABASE_URL is correct
- Ensure PostgreSQL is running (`psql -U postgres -d postgres -c "SELECT 1"`)

**"relation 'users' does not exist":**
- Tests should auto-create schema; if not, manually run:
  ```python
  python -c "from app.db import engine, Base; import asyncio; asyncio.run(engine.run_sync(Base.metadata.create_all))"
  ```

