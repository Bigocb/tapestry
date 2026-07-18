# MEMIND: AI-Powered Memory Capture & Enhancement Platform - PRD

## Problem Statement

Users want to capture their experiences, thoughts, and memories in real-time—but raw captures are often fragmented, vague, or lack important context. There's no efficient way to:
- Quickly record voice memos, text, or structured inputs without friction
- Automatically parse and refine rambling captures into coherent, searchable memories
- Discover connections between memories and build narratives from them
- Search and retrieve memories meaningfully (not just by keywords)
- Reflect on memories and create stories from them

Existing solutions (Notes, Notion, Diaries) lack intelligent agent support for refinement and story-building.

## Solution

MEMIND is a multi-user AI-powered platform that:
1. **Captures memories** via voice, text, or form inputs (synchronous, instant feedback)
2. **Automatically refines** raw captures through a pipeline of specialized AI agents (asynchronous background processing)
3. **Enriches memories** with extracted entities, related memories via RAG, tags, and context
4. **Provides hybrid search** (full-text + semantic + structured filters)
5. **Generates narratives** by stitching memories together into coherent stories
6. **Offers rich editing** for manual refinement and curation
7. **Displays timelines** of memories for chronological browsing
8. **Provides insights & gamification** ("fun area") for reflection and engagement

The system uses **Ollama Cloud API** for primary LLM tasks (open-source models) with **Claude Opus fallback** for complex story generation. All processing is asynchronous after the initial capture, so the user experience is responsive.

---

## User Stories

### Capture & Input

1. As a busy professional, I want to record voice memos hands-free while commuting, so that I can capture thoughts without typing
2. As a reflective person, I want to dump raw text quickly without worrying about structure, so that I can capture before forgetting
3. As a form-focused user, I want to fill out structured prompts (mood, people, location, time) when capturing, so that initial metadata is rich
4. As a multi-input user, I want to mix capture methods—sometimes voice, sometimes text, sometimes form, so that I can use the right tool for the moment
5. As a user, I want my capture to be saved immediately even if agents are still processing, so that I don't lose data
6. As a user, I want to see my transcribed voice memo instantly, so that I can verify it captured correctly before it's processed

### Refinement & Agent Processing

7. As a user with messy captures, I want an agent to turn my rambling into a structured summary, so that I can understand what I captured at a glance
8. As someone with vague references, I want an agent to resolve ambiguities ("that meeting" → "Q3 planning meeting on July 15"), so that context is clear
9. As a user, I want agents to normalize dates, names, and entities automatically, so that I don't have to clean up manually
10. As a data-conscious user, I want to see how the agent refined my memory and manually correct it if needed, so that I have control
11. As a user, I want the refinement process to happen in the background without blocking me, so that the UI stays responsive
12. As a user, I want to know when processing is complete, so that I can review the final memory (via webhooks, notifications, or polling)

### Enrichment & RAG

13. As a user, I want the system to find similar past memories when enriching a new one, so that I can see patterns and connections
14. As a user, I want agents to suggest tags based on similar memories and content, so that I don't manually tag everything
15. As a user, I want agents to set importance levels (1-10) intelligently, so that crucial memories stand out
16. As a user, I want to see which memories are related to mine, so that I can navigate clusters of experience

### Search & Discovery

17. As a user, I want to search by text ("coffee with Sarah"), so that I can find specific memories
18. As a user, I want to search semantically ("conversations about career growth"), so that I find conceptually similar memories even if keywords differ
19. As a user, I want to filter by date, mood, tags, and importance, so that I can narrow results
20. As a user, I want a unified search that combines text + semantic + filters, so that I get the best of all worlds
21. As a user, I want to use natural language queries ("Tell me about my manager conversations in Q1"), so that the search feels conversational
22. As a power user, I want faceted search results showing filters I can apply, so that I can explore my memories

### Editing & Curation

23. As a user, I want a rich text editor to refine my memories after capture, so that I can add details or fix issues
24. As a user, I want to click entity tags and edit them directly, so that I can correct extracted information
25. As a user, I want to see related memories in a sidebar while editing, so that I can add context or cross-references
26. As a user, I want auto-save while editing, so that I don't lose changes
27. As a user, I want to change the mood and importance level of a memory, so that I can recategorize over time

### Timeline & Browsing

28. As a user, I want to see all my memories in a chronological timeline, so that I can visualize my life progression
29. As a user, I want to filter the timeline by date range, tags, or mood, so that I can focus on specific periods
30. As a user, I want to click on timeline entries to expand and view/edit, so that I can interact with memories easily
31. As a user, I want the timeline to be visual and engaging, so that reviewing memories is enjoyable

### Story Generation & Narrative

32. As a user, I want to select a set of memories and generate a chronological story, so that I can see the timeline of an event
33. As a user, I want to generate a thematic story connecting similar memories, so that I can understand recurring themes
34. As a user, I want a "curated highlight reel" of my most important memories, so that I can quickly see my best moments
35. As a user, I want weekly/monthly digest stories auto-generated, so that I have recaps without work
36. As a user, I want to provide a custom prompt for story generation ("Make this funny," "Focus on lessons learned"), so that the narrative tone matches my intent
37. As a user, I want stories to be coherent and readable prose with transitions, not just a list, so that they feel like real narratives
38. As a user, I want to export stories in multiple formats (markdown, PDF, plain text), so that I can share or print them
39. As a user, I want to see which memories were used in a story, so that I can trace back to originals

### Insights & Gamification ("Fun Area")

40. As a reflective user, I want to see stats about my memories (total count, by mood, by tag), so that I can understand my memory patterns
41. As a user, I want to see trends over time (memories per week, mood trends, tag frequencies), so that I can spot patterns in my life
42. As a user, I want a word cloud of frequent words in my memories, so that I can see what occupies my mind
43. As a user, I want to earn badges/achievements (e.g., "100 memories captured," "First story generated"), so that capturing and engaging feels rewarding
44. As a user, I want to see my "streak" of daily captures, so that I'm motivated to journal consistently
45. As a user, I want memory stats to be visualized (charts, graphs), so that insights are easy to digest

### Multi-User & Collaboration

46. As a user, I want to create an account with secure authentication, so that only I can see my memories
47. As a user, I want my memories to be completely isolated from other users, so that privacy is guaranteed
48. As a potential user, I want to sign up easily, so that I can start capturing quickly
49. As a team using MEMIND, I want shared workspaces (future enhancement), so that we can have shared memory repositories
50. As a user, I want session management and token refresh, so that I stay securely logged in

---

## Implementation Decisions

### Architecture & Tech Stack

- **Backend:** Python 3.11+ with FastAPI for REST API and agent orchestration
- **Data Models:** Pydantic v2 for schema validation, serialization, and type safety across all layers
- **Database:** PostgreSQL 15+ on Render with pgvector extension for both structured data and vector embeddings
- **Vector Search:** Use pgvector (built into Postgres) instead of external vector DB (Pinecone, Weaviate) to keep infrastructure simple and reduce dependencies
- **LLM Strategy:** Ollama Cloud API for primary tasks (open-source models like Mistral, Llama) with Claude Opus fallback for story generation quality
- **Voice Transcription:** Whisper model via Ollama for voice-to-text conversion
- **Async Processing:** APScheduler or Celery for background agent jobs (refinement, enrichment, story generation)
- **Frontend:** React/Next.js for rich UI with real-time updates, timelines, editors
- **Authentication:** JWT-based stateless auth with user_id in token claims
- **Deployment:** Render for FastAPI service and PostgreSQL database

### Data Model & Schema

**Core Tables:**
- `users` - User accounts with hashed passwords
- `memories` - Core memory storage with processing state machine (raw → capturing → refined → enriching → enriched → ready)
- `entities` - Extracted entities (person, place, date, event, concept) with metadata
- `stories` - Generated narratives linked to source memories
- `job_status` - Track async agent job progress and state

**Processing State Machine:**
Each memory transitions through: `raw` → `capturing` → `refined` → `enriching` → `enriched` → `ready`

User sees immediate `raw` state feedback; final `ready` state includes all enrichment.

**Embedding Strategy:**
- Generate embeddings using Ollama's embedding model (not chat completion)
- Store in pgvector column (dimension depends on model, typically 384-1536)
- Use cosine similarity for semantic search

**JSONB for Flexibility:**
- `structured_content` (JSONB) stores Title, Summary, Entities, Mood, Tags—allows evolution without migrations
- `metadata` (JSONB) on entities allows rich, extensible entity data

### Agent Pipeline & Responsibilities

**Capture Agent (Ollama, ~1 second, synchronous):**
- Input: Raw text (transcribed voice, pasted text, or form data)
- Output: Structured JSON with title, summary, initial entities, mood
- Prompt focus: Clear structuring without ambiguity resolution
- User sees output immediately for verification

**Refinement Agent (Ollama, ~2-3 seconds, asynchronous):**
- Input: Structured memory + similar past memories from DB
- Output: Refined structured memory with resolved references, normalized entities
- Task: "That meeting" → "Q3 Planning on July 15"; standardize date formats; clarify pronouns
- Triggered after capture, runs in background

**Enrichment Agent (Ollama + RAG, ~3-5 seconds, asynchronous):**
- Input: Refined memory + vector embedding
- Process:
  1. Generate embedding via Ollama embeddings model
  2. Query pgvector for top-5 semantically similar memories
  3. Prompt agent to suggest tags, importance, thematic connections
- Output: Tags, related_memory_ids, importance_level, connection notes
- Triggered after refinement, runs in background

**Search Agent (Ollama, on-demand):**
- Input: Natural language user query
- Output: Structured SearchQuery object (text terms, semantic query, filters)
- Allows natural conversation: "Tell me about my manager chats in Q1" → {text: "manager", filters: {date_range: Q1}}

**Story Agent (Ollama-first, Claude Opus fallback, on-demand):**
- Input: Selected memories + story_type + optional custom prompt
- Output: Markdown narrative
- Story types:
  - **Chronological:** Timeline ("On [date]..., then..., finally...")
  - **Thematic:** Theme-based ("The thread of [theme] connects these moments...")
  - **Curated:** Best moments ("Here are your 5 most meaningful...")
  - **Digest:** Summary recap ("Weekly reflection: you experienced...")
- Fallback to Claude Opus if Ollama quality is poor (configurable threshold or manual flag)

### API Contract & Routes

**Memory Capture:**
```
POST /memories/capture
Body: multipart/form-data
  - audio_file (WAV/MP3 file, optional)
  - text (string, optional)
  - input_type (enum: voice, text, form)
  - mood (string, optional)
  - tags (array, optional)
Response: MemoryResponse with state="raw"
```

**Memory Retrieval:**
```
GET /memories/:id
GET /memories?page=1&limit=20
Response: List[MemoryResponse]
```

**Hybrid Search:**
```
POST /memories/search
Body:
  {
    "text": "coffee meeting",
    "semantic": "casual professional conversations",
    "filters": {
      "date_range": {"start": "2024-07-01", "end": "2024-07-31"},
      "tags": ["work", "social"],
      "mood": "happy",
      "importance_min": 5
    },
    "limit": 20
  }
Response: List[SearchResult] with relevance scores
```

**Story Generation:**
```
POST /stories/generate
Body:
  {
    "memory_ids": [uuid1, uuid2, uuid3],
    "story_type": "chronological",
    "custom_prompt": "Focus on lessons learned"
  }
Response: StoryResponse with generated narrative
```

**Timeline:**
```
GET /timeline?start_date=2024-07-01&end_date=2024-07-31&limit=50
Response: List[MemoryResponse] ordered by created_at DESC
```

**Insights:**
```
GET /insights/stats
GET /insights/trends
GET /insights/word-cloud
GET /insights/achievements
Response: JSON with stats, trends, word frequencies, badges
```

### Async Job Processing

- **Job Scheduler:** APScheduler for simplicity, Celery for scale
- **Job Storage:** PostgreSQL job_status table tracks: job_id, task_type, status, progress, error
- **Polling/Webhooks:** Client can poll `/jobs/{job_id}` or subscribe to webhooks for completion
- **Timeout Strategy:** Refinement (5s), Enrichment (10s), Story Generation (30s)

### User Isolation & Multi-User

- **JWT Token:** Contains user_id claim
- **Every query:** Filtered by `user_id` (database-level via WHERE clauses)
- **Workspace concept:** Each user is their own workspace; future: invite others to shared workspace
- **No cross-user data leakage:** Even if a bug surfaces a user_id, that user sees only their memories

### UI/Frontend Decisions

- **Capture Interface:** Modal/page with voice recorder (HTML5 audio), text area, quick mood/tag selector
- **Memory Editor:** Rich text editor (TipTap, Slate, or similar) with entity tag inline editing and sidebar of related memories
- **Timeline:** Infinite scroll or paginated, cards showing memory date + title + snippet
- **Search UI:** Unified search bar + faceted filters (date picker, tag chips, mood selector, importance slider)
- **Story Builder:** Memory selection (checkboxes), story type radio buttons, custom prompt textarea, generate button
- **Insights Dashboard:** Cards for stats, charts for trends, word cloud visualization, badge gallery

### Testing Strategy

**What makes a good test:**
- Tests external behavior (API responses, database state), not implementation details (internal agent logic)
- Isolated per component: tests for capture agent don't mock out database, but do mock Ollama API
- Integration tests verify end-to-end pipeline (capture → refinement → enrichment → search)
- Agent outputs are validated against Pydantic schemas to ensure consistency

**Modules to test:**
- **Capture Agent:** Input parsing, Pydantic output validation
- **Refinement Agent:** Entity resolution, date normalization, Pydantic output validation
- **Enrichment Agent:** Vector generation, pgvector similarity query accuracy, tag suggestion quality
- **Search:** Full-text search accuracy, semantic search via pgvector, filter composition
- **Story Generation:** Narrative coherence (manual review), story type variants
- **API Routes:** Happy path + error cases (404, 400, 401), pagination, sorting
- **Multi-user isolation:** Verify users can't see each other's memories, queries are scoped

**Prior Art:**
- FastAPI test client for API testing (pytest + httpx)
- Pydantic model testing: validate input/output shapes
- Mock Ollama API responses for agent tests (pytest fixtures)
- Seed test database with known memories for search tests

---

## Out of Scope

- **Real-time collaboration** (multiple users editing same memory) - future enhancement
- **Shared workspaces** - single-user isolation is core; sharing is phase 2
- **Mobile apps** (iOS/Android) - web-only initially; native apps future
- **Advanced encryption** - uses standard HTTPS/TLS; no end-to-end encryption planned
- **Complex integrations** (Slack, email import) - future enhancement
- **Memory deletion/archival policies** - simple hard delete for now
- **Fine-tuned LLM models** - use pre-trained Ollama + Claude, no fine-tuning
- **Audio storage/streaming** - transcribe immediately, discard audio files
- **Offline mode** - requires internet for agents

---

## Further Notes

### Rationale for Key Decisions

**Ollama-first with Claude fallback:**
- Ollama is cost-effective and privacy-respecting (models run open-source)
- Story generation is where quality matters most (more complex reasoning), so Claude Opus fallback ensures good narratives
- Easy to swap: if Ollama quality improves, no code change needed

**pgvector instead of external vector DB:**
- Simplifies infrastructure (one database, no extra managed service)
- Sufficient for personal/small-team scale
- Easy migration path: if scale demands it, extract embeddings and migrate to Weaviate/Pinecone

**Async pipeline:**
- Capture must be instant (user feedback); refinement/enrichment can be background
- Transparent to user: query a memory, get best-effort state (may be raw or enriched); user can poll/wait
- Easier to iterate: swap agents without blocking user

**Pydantic for everything:**
- Type safety across API, database, agents
- Validation happens at boundaries (API input, agent output)
- Serialization/deserialization is automatic and consistent
- Easy to evolve schemas (Pydantic migrations are cleaner than raw SQL)

### Phased Rollout

- **MVP (Phase 1):** Capture, Refinement Agent, basic search, simple React UI
- **Phase 2:** Full enrichment pipeline, hybrid search, timeline, rich editor
- **Phase 3:** Story generation, insights, multi-user auth
- **Phase 4:** Polish, advanced story variants, exports, gamification

### Success Metrics

- Users can capture a memory in <2 seconds (capture sync time)
- Refinement/enrichment completes in <10 seconds (async feedback time)
- Search returns results in <1 second (including semantic search via pgvector)
- Generated stories are coherent and readable (manual review)
- Users engage regularly (daily/weekly captures) = adoption signal

### Future Enhancements

- Shared workspaces for collaborative memory capture
- Memory suggestions ("You haven't captured anything in 3 days")
- Cross-memory reasoning (multi-hop: "Show me all people mentioned with Sarah")
- Export to common formats (Roam, Obsidian, Notion)
- Mobile apps with offline capture (queue for sync)
- Fine-tuned agents for specific user domains (work, personal, creative)
- Memory reminders ("On this day last year...")
- Emotion/sentiment analysis across memories

