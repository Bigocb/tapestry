# Tapestry: Memory Capture & Enrichment System

## Overview

Tapestry is a multi-user AI-powered memory capture and enhancement platform. Users record voice memos, text, or form submissions. Specialized AI agents parse, refine, enrich, and help users build narratives from their memories. Features include rich editing, timeline browsing, hybrid search, story generation, and a "fun area" for insights and gamification.

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Backend | Python 3.11+ / FastAPI | REST API, agent orchestration |
| Data Models | Pydantic v2 | Validation, serialization, schema |
| Database | PostgreSQL 15+ (Render) | Structured data + pgvector embeddings |
| Vector Search | pgvector | Semantic search without external DB |
| LLM Provider | Ollama Cloud API | Open-source models (Ollama-first) |
| LLM Fallback | Claude Opus (Anthropic) | Fallback for story generation quality |
| Voice Transcription | Whisper (Ollama) | Convert audio → text |
| Async Queue | APScheduler / Celery | Background agent processing |
| Frontend | React / Next.js | Rich UI, capture, search, timeline, editor |
| Auth | JWT + PostgreSQL | Multi-user, session management |
| Deployment | Render | FastAPI service + Postgres |

---

## Data Model (PostgreSQL + Pydantic)

### Core Tables

```sql
-- Users
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username VARCHAR(255) UNIQUE NOT NULL,
  email VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Memories
CREATE TABLE memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  
  -- Input & Raw Data
  raw_input TEXT NOT NULL,
  input_type VARCHAR(50) NOT NULL, -- 'voice', 'text', 'form'
  
  -- Structured Content (Pydantic model serialized to JSONB)
  structured_content JSONB,
  
  -- Embedding for semantic search
  embedding vector(1536), -- dimension depends on Ollama model
  
  -- Metadata
  tags TEXT[],
  mood VARCHAR(50),
  importance_level INT DEFAULT 5, -- 1-10
  
  -- Processing state
  processing_state VARCHAR(50) DEFAULT 'raw', 
  -- States: raw → capturing → refined → enriching → enriched → ready
  
  -- Relationships
  related_memory_ids UUID[],
  
  -- Timestamps
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Entities extracted from memories
CREATE TABLE entities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  
  type VARCHAR(50) NOT NULL, -- 'person', 'place', 'date', 'event', 'concept'
  value TEXT NOT NULL,
  metadata JSONB, -- extra info (e.g., date format, person role)
  
  created_at TIMESTAMP DEFAULT NOW()
);

-- Stories generated from memories
CREATE TABLE stories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  
  title VARCHAR(255) NOT NULL,
  narrative TEXT NOT NULL,
  memory_ids UUID[] NOT NULL,
  
  story_type VARCHAR(50), -- 'chronological', 'thematic', 'curated', 'digest'
  
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_memories_user_id ON memories(user_id);
CREATE INDEX idx_memories_created_at ON memories(created_at DESC);
CREATE INDEX idx_memories_tags ON memories USING GIN(tags);
CREATE INDEX idx_memories_embedding ON memories USING ivfflat(embedding vector_cosine_ops);
CREATE INDEX idx_entities_user_id ON entities(user_id);
CREATE INDEX idx_entities_memory_id ON entities(memory_id);
CREATE INDEX idx_stories_user_id ON stories(user_id);
```

### Pydantic Models

```python
# schemas.py

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID

# User Models
class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    created_at: datetime

# Entity Models
class EntityData(BaseModel):
    type: str  # 'person', 'place', 'date', 'event', 'concept'
    value: str
    metadata: Optional[dict] = None

# Memory Models
class StructuredMemory(BaseModel):
    title: str
    summary: str
    entities: List[EntityData]
    mood: Optional[str] = None
    importance_level: int = Field(default=5, ge=1, le=10)
    initial_tags: List[str] = []

class MemoryCapture(BaseModel):
    raw_input: str
    input_type: str  # 'voice', 'text', 'form'

class MemoryRefined(BaseModel):
    structured_content: StructuredMemory
    processing_state: str = "refined"

class MemoryEnriched(BaseModel):
    tags: List[str]
    related_memory_ids: List[UUID] = []
    processing_state: str = "enriched"

class MemoryResponse(BaseModel):
    id: UUID
    user_id: UUID
    raw_input: str
    input_type: str
    structured_content: StructuredMemory
    tags: List[str]
    mood: Optional[str]
    importance_level: int
    processing_state: str
    related_memory_ids: List[UUID]
    created_at: datetime
    updated_at: datetime

# Story Models
class StoryGenerate(BaseModel):
    memory_ids: List[UUID]
    story_type: str  # 'chronological', 'thematic', 'curated', 'digest'
    custom_prompt: Optional[str] = None

class StoryResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    narrative: str
    memory_ids: List[UUID]
    story_type: str
    created_at: datetime

# Search Models
class SearchQuery(BaseModel):
    text: Optional[str] = None
    semantic: Optional[str] = None  # semantic query
    filters: Optional[dict] = None  # date range, tags, mood, etc.
    limit: int = 20

class SearchResult(BaseModel):
    memory_id: UUID
    title: str
    summary: str
    score: float  # relevance score
    created_at: datetime
```

---

## Agent Workflow

### Pipeline Overview

```
1. INPUT (User → API)
   ↓
2. CAPTURE AGENT (Ollama, ~1s)
   Raw → Structured JSON
   ↓
3. REFINEMENT AGENT (Ollama, ~2-3s, async)
   Structured → Resolved, normalized
   ↓
4. ENRICHMENT AGENT (Ollama + RAG, ~3-5s, async)
   + Vector embedding
   + Retrieve similar memories
   + Add context & tags
   ↓
5. READY FOR USE
   (searchable, usable for stories)
```

### Agent Specifications

#### **Capture Agent**
- **Input:** Raw text (from voice transcription, text dump, or form)
- **Task:** Structure the rambling into title, summary, initial entities
- **LLM:** Ollama (Mistral or similar)
- **Prompt Template:**
  ```
  You are a memory structuring assistant. Parse this raw memory input and extract:
  - title (brief, 5-10 words)
  - summary (1-2 sentences)
  - entities (people, places, dates, events, concepts)
  - mood (happy, sad, neutral, excited, etc.)
  
  Input: {raw_input}
  
  Return JSON only.
  ```
- **Output:** StructuredMemory (Pydantic model)

#### **Refinement Agent**
- **Input:** StructuredMemory + context from DB
- **Task:** Clarify ambiguities, normalize entities, resolve references
- **LLM:** Ollama
- **Prompt Template:**
  ```
  You are a memory refinement assistant. Given this structured memory and context:
  
  Memory: {structured_memory}
  
  Similar past memories:
  {related_memories_context}
  
  Refine by:
  1. Resolving pronouns and vague references ("that meeting" → "team standup on 2024-07-15")
  2. Normalizing dates and names
  3. Adding clarifying details from context
  
  Return updated JSON.
  ```
- **Output:** Refined StructuredMemory

#### **Enrichment Agent**
- **Input:** Refined memory + vector embedding + RAG results
- **Task:** Generate embeddings, retrieve similar memories, suggest tags/context
- **LLM:** Ollama
- **Process:**
  1. Generate embedding for memory (using Ollama embeddings model)
  2. Query pgvector for top-5 similar memories
  3. Prompt agent to suggest tags and connections
- **Prompt Template:**
  ```
  You are a memory enrichment assistant. Given:
  
  Current memory: {memory_title}
  Similar past memories: {top_5_similar}
  
  Suggest:
  1. Tags (3-5) to categorize this memory
  2. Thematic connections to related memories
  3. Importance level (1-10)
  4. Any missing context to capture
  
  Return JSON.
  ```
- **Output:** Tags, related_memory_ids, updated importance_level

#### **Search Agent**
- **Input:** User query (natural language)
- **Task:** Interpret query, build hybrid search command
- **LLM:** Ollama
- **Prompt:**
  ```
  Convert this query into search parameters:
  - text: full-text search terms
  - semantic: semantic search query
  - filters: date ranges, tags, mood
  
  Query: {user_query}
  
  Return JSON.
  ```
- **Output:** SearchQuery (structured parameters)

#### **Story Agent**
- **Input:** Selected memories + story_type + optional custom prompt
- **Task:** Generate narrative, stitch memories together
- **LLM:** Ollama-first, fallback Claude Opus
- **Variants:**
  - **Chronological:** Timeline narrative ("On [date], you experienced...")
  - **Thematic:** Theme-based ("The recurring theme of [theme] appears in...")
  - **Curated:** Highlight reel ("Here are your most meaningful moments...")
  - **Digest:** Summary ("Weekly recap of your memories...")
- **Prompt Template:**
  ```
  You are a storyteller. Create a {story_type} narrative from these memories:
  
  Memories:
  {memory_list}
  
  Style: Engaging, personal, coherent narrative that connects the memories.
  
  {custom_prompt or ""}
  
  Return markdown narrative.
  ```
- **Output:** StoryResponse

---

## API Routes

### Authentication
```
POST   /auth/register         - Create user account
POST   /auth/login            - Get JWT token
POST   /auth/refresh          - Refresh token
```

### Memory Management
```
POST   /memories/capture              - Submit voice/text/form
  - accepts multipart form data (audio file or text)
  - returns: MemoryResponse (will be in 'raw' state)

GET    /memories/:id                  - Retrieve memory
GET    /memories                      - List user's memories (paginated)
PATCH  /memories/:id                  - Manual refinement/editing
DELETE /memories/:id                  - Delete memory

GET    /memories/search               - Hybrid search
  - query params: text, semantic, filters, limit
  - returns: List[SearchResult]

GET    /memories/:id/related          - Get related memories (via RAG)
```

### Stories
```
POST   /stories/generate              - Create story from memories
  - body: StoryGenerate
  - returns: StoryResponse

GET    /stories/:id                   - Retrieve story
GET    /stories                       - List user's stories

POST   /stories/:id/export            - Export story
  - query param: format (markdown, pdf, txt)
```

### Timeline
```
GET    /timeline                      - Get memories for timeline view
  - query params: start_date, end_date, limit
  - returns: List of memories ordered chronologically
```

### Fun Area (Insights & Stats)
```
GET    /insights/stats                - Memory stats (total, by mood, etc.)
GET    /insights/trends               - Over-time trends (memories per week, etc.)
GET    /insights/word-cloud           - Word frequency from all memories
GET    /insights/achievements         - Gamification badges/milestones
```

---

## Frontend Architecture (React / Next.js)

### Key Pages/Components

1. **Capture Page** (`/capture`)
   - Voice recorder (WebRTC or audio input)
   - Text textarea
   - Quick form (mood, date, tags)
   - Real-time transcription display
   - Submit button

2. **Memory Editor** (`/memories/:id/edit`)
   - Rich text editor (for raw_input or structured_content)
   - Entity tags (clickable, editable)
   - Mood/importance selector
   - Auto-save
   - Show related memories in sidebar

3. **Search** (`/search`)
   - Unified search bar (text + semantic)
   - Filter panel (date range, tags, mood, importance)
   - Results displayed as cards with relevance score
   - Click to view full memory

4. **Timeline** (`/timeline`)
   - Chronological view of all memories
   - Date picker for range
   - Cards show title + snippet
   - Click to expand/edit

5. **Story Builder** (`/stories`)
   - Select memories (checkboxes)
   - Choose story type (chronological, thematic, curated, digest)
   - Optional custom prompt
   - Generate button
   - View/export generated narrative

6. **Fun Area** (`/insights`)
   - Memory stats dashboard
   - Word cloud visualization
   - Mood timeline chart
   - Achievements/badges
   - Weekly/monthly recap cards

---

## Async Job Processing

Use **APScheduler** or **Celery** for background tasks:

- **Refinement job:** Runs 1-2s after capture
- **Enrichment job:** Runs 3-5s after refinement
- **Story generation:** Long-running (up to 30s), user can check status

Job queue stores state in DB:
```python
class JobStatus(BaseModel):
    job_id: UUID
    memory_id: UUID
    task_type: str  # 'refinement', 'enrichment', 'story'
    status: str  # 'pending', 'running', 'completed', 'failed'
    progress: float  # 0-1
    error: Optional[str]
```

---

## Multi-User & Security

- **JWT authentication:** Stateless, user ID in token
- **User isolation:** All queries filtered by `user_id`
- **Password hashing:** bcrypt or argon2
- **CORS:** Frontend origin whitelisting
- **Rate limiting:** Per-user API rate limits
- **Workspace concept:** Each user is their own workspace

---

## Deployment (Render)

1. **PostgreSQL:** Create via Render dashboard with pgvector extension
2. **FastAPI Service:** Deploy Python app to Render web service
3. **Environment Variables:**
   - `DATABASE_URL`
   - `OLLAMA_API_KEY`
   - `OLLAMA_BASE_URL`
   - `CLAUDE_API_KEY` (fallback)
   - `JWT_SECRET_KEY`

---

## Development Roadmap

### Phase 1 (MVP)
- Pydantic models + FastAPI skeleton
- Postgres + pgvector setup
- Voice capture → transcription
- Capture Agent (basic structuring)
- Basic React UI (capture + list)

### Phase 2
- Refinement + Enrichment agents
- Hybrid search
- Memory editor UI
- Timeline view

### Phase 3
- Story generation
- Story builder UI
- Multi-user auth
- Fun area (insights)

### Phase 4
- Polish, performance optimization
- Advanced story variants
- Export formats (PDF, etc.)
- Gamification elements

---

## Key Design Decisions

1. **Ollama-first, Claude fallback** - Cost & speed first, quality upgrade only when needed
2. **pgvector in Postgres** - Single DB, no external vector store
3. **Async processing** - Capture instant, refinement/enrichment in background
4. **Pydantic for everything** - Type safety, validation, clean API contracts
5. **User-scoped queries** - Every table has user_id for multi-user isolation
6. **Specialized agents** - Clear responsibilities, easier testing & iteration

