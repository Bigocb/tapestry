# MEMIND Issues - Vertical Slices

> **Status snapshot** — last reconciled 2026-09-29 against `master` @ `4cb7df2`.
>
> **Done (verified by code + tests):** Issues 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 28, 29, 30, 31, 32, 33
> **Partial:** Issue 1 (Postgres is now provisioned, but **the pgvector extension is not installed** — the database has only `plpgsql`; the schema, indexes and cross-DB type decorators are in place), Issue 7 (embeddings work via Ollama with a deterministic local fallback; **similarity is still computed in Python** — no ANN index, because pgvector is absent)
> **Superseded:** Issue 27 — the deployment target changed. MEMIND runs in Docker Compose with Postgres on the homelab box, published through Traefik and cloudflared at `memory.cloutier.work`. The service is live; the Render-specific acceptance criteria no longer apply.
> **Not started:** Phase 9, Issues 34–36 (Tellings). Issues 28–33 are done, deployed and verified: the tracer bullet, segmentation, the date cursor, the telling's frame, reshaping the split, and undoing a commit.
>
> **Key deviations from original plan:**
> - **Storage:** production runs on Postgres 16 in Docker on the homelab box. SQLite (`memind.db`) remains the local-dev default.
> - **Search:** full-text + semantic ranking done in Python over fetched rows, not Postgres `tsquery`/pgvector ANN.
> - **Agents:** Ollama Cloud (`ollama.com/v1`, `gemma4:31b`) is primary. Story generation implements a Claude Opus fallback (`ANTHROPIC_API_KEY`), gated on a response-quality check; capture/refinement/enrichment are Ollama-only.
> - **Transcription:** local `faster-whisper`; Issue 4's backend is wired. A 501 is still returned when the model or its dependency is genuinely unavailable — that is error handling, not the old stub.
> - **Tests:** 435 backend passing, 1 skipped (the pgvector extension check) on in-memory SQLite, plus 27 frontend tests via vitest/jsdom.
> - **Beyond the plan:** first-class entities, the privacy lock, the review queue and fuzzy dates all shipped outside the numbered issues, so this list understates the delivered surface.
>
> **Remaining work:** the pgvector half of Issue 1 (and the ANN search it would unblock in Issue 7), Phase 9 (Tellings, Issues 28–35), and active iteration on capture/parsing quality (Issues 4–6 area).

---

## PHASE 1: Foundation & Infrastructure

### Issue 1: Set up Postgres with pgvector on Render

**Type:** AFK (but requires Render account interaction)  
**Blocked by:** None - can start immediately  
**User stories covered:** All (foundational)

#### What to build

Create a PostgreSQL 15+ instance on Render with the pgvector extension enabled. Configure connection pooling and create the base schema including `users`, `memories`, `entities`, `stories` tables with proper indexes. Verify pgvector is installed and operational with a test embedding insert.

#### Acceptance criteria

- [ ] PostgreSQL 15+ instance created on Render
- [x] pgvector extension installed and enabled
- [x] Base schema created (users, memories, entities, stories tables)
- [x] Proper indexes created for performance (user_id, created_at, tags GIN, embedding ivfflat)
- [x] Connection string available (DATABASE_URL env var documented)
- [x] Test: Insert a test memory with embedding and query it via pgvector

> **Status: PARTIAL.** Schema, indexes and cross-DB type decorators are in place, and Postgres is provisioned (Docker, on the homelab box). **The pgvector extension is not installed** — the database has only `plpgsql` — so the pgvector criteria and the ivfflat index remain unmet and the extension check is still skipped. Render is no longer the target; see Issue 27.

---

### Issue 2: Initialize FastAPI project structure & Pydantic models

**Type:** AFK  
**Blocked by:** None - can start immediately  
**User stories covered:** All (foundational)

#### What to build

Set up a Python FastAPI project with:
- Project structure (app/, routes/, models/, agents/, config/)
- Pydantic v2 schemas for all data models (User, Memory, Entity, Story, SearchQuery, etc.)
- Database connection setup (SQLAlchemy with async support)
- Basic configuration (environment variables, logging)
- Docker/deployment scaffolding

Pydantic models should match the schema design in ARCHITECTURE.md: StructuredMemory, MemoryCapture, MemoryResponse, EntityData, StoryResponse, etc.

#### Acceptance criteria

- [x] FastAPI project initialized with proper directory structure
- [x] All Pydantic models defined and tested for validation
- [x] Database connection established (async SQLAlchemy)
- [x] Environment variable loading (python-dotenv or Pydantic settings)
- [x] Logging configured
- [x] README with setup instructions (poetry install, env vars, run)
- [x] Test: Can import all models and validate basic data shapes

---

### Issue 3: Implement JWT authentication & user management

**Type:** AFK  
**Blocked by:** Issue 1 (Postgres), Issue 2 (FastAPI structure)  
**User stories covered:** 46, 47, 48, 50

#### What to build

Implement user registration, login, token refresh, and middleware to extract user_id from JWT token.

- Register endpoint: Create user with username, email, password (hashed with bcrypt/argon2)
- Login endpoint: Authenticate user, return JWT token
- Token refresh: Extend session
- Auth middleware: Extract user_id from token, inject into request context
- Dependency injection: get_current_user() for protected routes

Ensure all protected routes filter queries by user_id.

#### Acceptance criteria

- [x] POST /auth/register endpoint works (creates user, returns JWT)
- [x] POST /auth/login endpoint works (validates password, returns JWT)
- [x] JWT tokens contain user_id claim and expire correctly
- [x] POST /auth/refresh endpoint extends session
- [x] Auth middleware extracts user_id from token
- [x] get_current_user() dependency works in protected routes
- [x] Test: Can register, login, and access protected routes; cannot access other user's data

---

## PHASE 2: Core Memory Capture & Processing

### Issue 4: Implement memory capture API (voice/text/form)

**Type:** AFK  
**Blocked by:** Issue 3 (auth)  
**User stories covered:** 1, 2, 3, 4, 5, 6

#### What to build

Create POST /memories/capture endpoint that accepts:
- Voice files (WAV/MP3 from HTML5 audio recorder)
- Raw text input
- Form data (structured mood, tags, etc.)

Endpoint should:
1. Validate input (Pydantic)
2. Transcribe voice if audio file (call Whisper via Ollama)
3. Create memory record in DB with state='raw'
4. Return MemoryResponse immediately (synchronous)
5. Schedule refinement agent to run async in background

Support multipart form data for file uploads.

#### Acceptance criteria

- [x] POST /memories/capture accepts voice (audio file), text, and form data
- [x] Multipart form data handling works
- [ ] Voice transcription via Ollama Whisper works
- [x] Memory created in DB with state='raw'
- [x] User sees response immediately (state='raw')
- [x] Async refinement job scheduled in background
- [x] Test: Can capture voice/text, get immediate response, verify DB state

> **Status: DONE.** Text/form capture, `state='raw'` and background scheduling all work. Voice is transcribed locally with `faster-whisper`, decoded off the event loop, cached per model, and spooled to a temp file (the library does not accept raw bytes). A 501 is returned only when the model or its dependency is genuinely unavailable — error handling, not a stub.

---

### Issue 5: Implement Capture Agent (Ollama - structure raw input)

**Type:** AFK  
**Blocked by:** Issue 2 (Pydantic models), Issue 4 (memory capture)  
**User stories covered:** 7, 8

#### What to build

Create Capture Agent that:
- Takes raw input (text from voice transcript, text dump, or form)
- Calls Ollama Chat API with structured prompt
- Extracts and validates response into StructuredMemory Pydantic model
- Returns title, summary, entities, mood, initial_tags

Agent runs synchronously as part of POST /memories/capture response (should be ~1 second).

Prompt template should focus on clear structuring without ambiguity resolution (that's refinement's job).

#### Acceptance criteria

- [x] Capture Agent calls Ollama API with correct prompt
- [x] Response parsed into StructuredMemory Pydantic model
- [x] Validation ensures all required fields present
- [x] Returns within ~1 second
- [x] Handles Ollama API errors gracefully (fallback response)
- [x] Test: Feed rambling text, get structured JSON with title/summary/entities

---

### Issue 6: Implement Refinement Agent (Ollama - resolve ambiguities)

**Type:** AFK  
**Blocked by:** Issue 5 (Capture Agent)  
**User stories covered:** 8, 9, 10, 11, 12

#### What to build

Create Refinement Agent that runs asynchronously (via APScheduler) after capture:
- Takes StructuredMemory + similar past memories from DB
- Calls Ollama Chat API to resolve ambiguities (e.g., "that meeting" → specific date/event)
- Normalizes dates, names, entities
- Returns refined StructuredMemory
- Updates memory record with state='refined'

Prompt includes retrieved similar memories for context.

Job scheduler should:
- Trigger automatically after memory is captured
- Update memory processing_state as it progresses
- Handle failures gracefully (log error, mark state='refined_failed')

#### Acceptance criteria

- [x] Refinement Agent scheduled async after capture
- [x] Calls Ollama with prompt including similar memories
- [x] Resolves ambiguous references (vague pronouns, implicit references)
- [x] Normalizes dates (various formats → ISO 8601)
- [x] Updates memory state to 'refined'
- [x] Completes in ~2-3 seconds
- [x] Handles errors without crashing
- [x] Test: Capture with vague reference ("that meeting"), verify refinement resolves it

---

### Issue 7: Implement vector embeddings & semantic search foundation

**Type:** AFK  
**Blocked by:** Issue 1 (pgvector), Issue 2 (Pydantic models)  
**User stories covered:** 13, 16, 18, 22

#### What to build

Create embeddings infrastructure:
- Function to generate embeddings via Ollama embeddings API (not chat completion)
- Store embeddings in pgvector column (dimension depends on model, document: 384 or 1536)
- Implement pgvector similarity search (cosine distance)
- Retrieve top-K similar memories given a query string or embedding

This is used by:
1. Enrichment Agent (retrieve related memories before enrichment)
2. Semantic search in Search Agent
3. Story Agent (find thematic connections)

#### Acceptance criteria

- [x] Ollama embeddings API integration works (generate_embedding function)
- [ ] Embeddings stored in pgvector column (correct dimension)
- [x] Similarity search function returns top-K most similar memories
- [ ] Queries by cosine distance (pgvector similarity)
- [x] Test: Insert memory with embedding, query by semantic similarity, verify results

> **Status: PARTIAL.** `generate_embedding` calls the Ollama embeddings API (`nomic-embed-text`) with a deterministic 384-dim local fallback. Embeddings are serialized JSON strings in an unbounded `Text` column — the original `String(3000)` silently overflowed once the data reached Postgres, where the limit is enforced. Cosine similarity is still computed **in Python**; migrating to a native `vector` column + ivfflat index is blocked on the pgvector extension (Issue 1).

---

### Issue 8: Implement Enrichment Agent (Ollama + RAG)

**Type:** AFK  
**Blocked by:** Issue 6 (Refinement), Issue 7 (embeddings & similarity search)  
**User stories covered:** 13, 14, 15, 16

#### What to build

Create Enrichment Agent that runs asynchronously after refinement:
1. Generate embedding for refined memory via Ollama embeddings API
2. Query pgvector for top-5 similar memories (RAG retrieval)
3. Call Ollama Chat API with refined memory + similar memories context
4. Agent suggests: tags, importance_level (1-10), thematic connections, related_memory_ids
5. Update memory with tags, importance, related_memory_ids
6. Update memory state='enriched'

Prompt should leverage similar memories to inform suggestions.

#### Acceptance criteria

- [x] Generates embedding via Ollama embeddings API
- [x] Retrieves top-5 similar memories from pgvector
- [x] Calls Ollama Chat API with context from similar memories
- [x] Suggests tags, importance level, related memory links
- [x] Updates memory state to 'enriched'
- [x] Completes in ~3-5 seconds
- [x] Test: Enrich a memory, verify tags/importance/related links are reasonable

> **Status: DONE.** Note: "pgvector" retrieval is currently in-Python cosine similarity over the user's memories (see Issue 7).

---

## PHASE 3: Search & Discovery

### Issue 9: Implement hybrid search (full-text + semantic + filters)

**Type:** AFK  
**Blocked by:** Issue 8 (Enrichment), Issue 7 (embeddings)  
**User stories covered:** 17, 18, 19, 20, 21, 22

#### What to build

Create POST /memories/search endpoint that performs hybrid search:

**Full-text search:**
- Query title, summary, raw_input using PostgreSQL full-text search (tsquery)
- Return relevance score

**Semantic search:**
- Convert user query to embedding via Ollama
- Query pgvector for similar memories by cosine distance
- Return similarity score

**Structured filters:**
- Date range (created_at >= start, <= end)
- Tags (INTERSECT with user-provided tags)
- Mood (exact match or list)
- Importance level (>= min_importance)

**Ranking:**
- Combine scores (e.g., weighted: 0.3*full_text + 0.4*semantic + 0.3*filter_bonus)
- Return ranked list of SearchResult objects

#### Acceptance criteria

- [x] POST /memories/search endpoint accepts text, semantic, filters
- [ ] Full-text search via PostgreSQL tsquery works
- [ ] Semantic search via pgvector works
- [x] Structured filters (date, tags, mood, importance) work
- [x] Results ranked by combined relevance score
- [x] Pagination supported (limit, offset)
- [x] Returns within ~1 second (including semantic search)
- [x] Test: Search by text ("coffee"), semantic ("casual meetings"), filters (mood=happy), combinations

> **Status: DONE (ranking deviation).** Weighting matches the plan (0.3 full-text + 0.4 semantic + 0.3 filter bonus), but scoring runs in Python: substring term-matching for full-text and cosine similarity over serialized embeddings. Native Postgres `tsquery` + pgvector ANN are deferred to Issue 27.

---

### Issue 10: Implement Search Agent (interpret natural language queries)

**Type:** AFK  
**Blocked by:** Issue 9 (hybrid search)  
**User stories covered:** 21

#### What to build

Create Search Agent that:
- Takes natural language user query (e.g., "Tell me about my manager conversations in Q1")
- Calls Ollama Chat API to parse into SearchQuery components:
  - text: relevant keywords
  - semantic: semantic interpretation of the query
  - filters: inferred date range, tags, mood, etc.
- Validates output as SearchQuery Pydantic model
- Passes to hybrid search (Issue 9)

Optional: Expose as POST /memories/search/natural endpoint, or integrate into POST /memories/search.

#### Acceptance criteria

- [x] Parses natural language to structured SearchQuery
- [x] Extracts text keywords, semantic intent, filters
- [x] Handles time expressions ("Q1", "last month", "this week")
- [x] Integrates with hybrid search from Issue 9
- [x] Test: Query "manager conversations in Q1", verify parsed correctly and returns results

---

## PHASE 4: Memory Management & Editing

### Issue 11: Implement memory retrieval & listing endpoints

**Type:** AFK  
**Blocked by:** Issue 3 (auth)  
**User stories covered:** None (foundational for UI)

#### What to build

Create read endpoints:
- GET /memories/:id - Retrieve single memory with all details
- GET /memories - List user's memories with pagination (limit, offset, sort by created_at DESC)
- Response: MemoryResponse objects (full structure)

All queries filtered by current user_id.

#### Acceptance criteria

- [x] GET /memories/:id returns full MemoryResponse
- [x] GET /memories returns paginated list of user's memories
- [x] Pagination supports limit, offset, sort
- [x] 404 if memory doesn't exist or belongs to different user
- [x] Test: Create memory, retrieve by ID, list memories

---

### Issue 12: Implement memory editing (PATCH /memories/:id)

**Type:** AFK  
**Blocked by:** Issue 11 (retrieval)  
**User stories covered:** 23, 24, 25, 26, 27

#### What to build

Create PATCH /memories/:id endpoint to allow manual refinement:
- Update raw_input (raw text)
- Update structured_content (title, summary, entities, mood)
- Update tags (add/remove)
- Update mood and importance_level
- Update related_memory_ids (manual corrections to RAG links)
- Auto-save on each update

Changes validated against Pydantic models. Update memory updated_at timestamp.

#### Acceptance criteria

- [x] PATCH /memories/:id accepts partial updates
- [x] Can update title, summary, entities, mood, tags, importance
- [x] Pydantic validation on updates
- [x] 404 if memory doesn't exist or belongs to different user
- [x] Updated_at timestamp updated
- [x] Test: Edit memory, verify changes persist

---

### Issue 13: Implement memory deletion

**Type:** AFK  
**Blocked by:** Issue 11 (retrieval)  
**User stories covered:** None (foundational)

#### What to build

Create DELETE /memories/:id endpoint:
- Hard delete memory and associated entities/stories
- Cascade delete (entities linked to this memory are deleted)
- 404 if memory doesn't exist or belongs to different user

#### Acceptance criteria

- [x] DELETE /memories/:id removes memory and associated records
- [x] Cascade delete for entities
- [x] 404 if memory doesn't exist or belongs to different user
- [x] Test: Delete memory, verify it's gone from DB

---

## PHASE 5: Story Generation & Narrative

### Issue 14: Implement Story Agent (Ollama-first, Claude fallback)

**Type:** AFK  
**Blocked by:** Issue 8 (Enrichment - memories are enriched and ready)  
**User stories covered:** 32, 33, 34, 35, 36, 37, 38, 39

#### What to build

Create Story Agent that:
- Takes selected memory_ids, story_type, optional custom_prompt
- Retrieves full memories from DB
- Calls Ollama Chat API with story prompt (variants: chronological, thematic, curated, digest)
- If Ollama response quality is poor (optional: check response length/coherence), fallback to Claude Opus
- Returns markdown narrative

Story types:
- **Chronological:** Timeline narrative ("On [date]..., then...")
- **Thematic:** Theme-based ("The thread of [theme]...")
- **Curated:** Best moments ("Here are your most meaningful...")
- **Digest:** Weekly/monthly recap

#### Acceptance criteria

- [x] Story Agent calls Ollama Chat API with story prompts
- [x] Generates coherent narrative (tested manually)
- [x] Supports all 4 story types
- [x] Falls back to Claude Opus if configured/needed
- [x] Handles custom prompts (user-provided tone/focus)
- [x] Returns markdown narrative
- [x] Test: Generate chronological story from 3 memories, verify narrative makes sense

---

### Issue 15: Implement story generation API (POST /stories/generate)

**Type:** AFK  
**Blocked by:** Issue 14 (Story Agent)  
**User stories covered:** 32, 33, 34, 35, 36

#### What to build

Create POST /stories/generate endpoint:
- Body: StoryGenerate (memory_ids, story_type, custom_prompt)
- Validate memory_ids belong to current user
- Call Story Agent (Issue 14)
- Create story record in DB
- Return StoryResponse with generated narrative

#### Acceptance criteria

- [x] POST /stories/generate accepts StoryGenerate
- [x] Validates memory ownership
- [x] Calls Story Agent
- [x] Creates story record in DB
- [x] Returns StoryResponse with narrative
- [x] Test: Generate story from memories, verify it's stored

---

### Issue 16: Implement story retrieval & export

**Type:** AFK  
**Blocked by:** Issue 15 (story generation)  
**User stories covered:** 38, 39

#### What to build

Create endpoints:
- GET /stories/:id - Retrieve story with narrative
- GET /stories - List user's stories
- POST /stories/:id/export - Export story to format (markdown, txt, json)

#### Acceptance criteria

- [x] GET /stories/:id returns full StoryResponse
- [x] GET /stories returns user's stories paginated
- [x] POST /stories/:id/export supports markdown, txt, json formats
- [x] 404 if story doesn't exist or belongs to different user
- [x] Test: Generate story, retrieve it, export to markdown

---

## PHASE 6: Timeline & Insights

### Issue 17: Implement timeline endpoint (GET /timeline)

**Type:** AFK  
**Blocked by:** Issue 11 (memory retrieval)  
**User stories covered:** 28, 29, 30

#### What to build

Create GET /timeline endpoint:
- Query params: start_date, end_date, limit
- Return memories in chronological order (created_at DESC or ASC)
- Support filtering by date range, tags, mood
- Pagination

Response: List of MemoryResponse objects ordered by date.

#### Acceptance criteria

- [x] GET /timeline returns memories chronologically ordered
- [x] Supports date range filtering (start_date, end_date)
- [x] Supports tag/mood filters
- [x] Pagination (limit, offset)
- [x] Test: Retrieve timeline for date range, verify chronological order

---

### Issue 18: Implement insights/stats endpoints (GET /insights/*)

**Type:** AFK  
**Blocked by:** Issue 8 (Enrichment - memories enriched with tags/mood)  
**User stories covered:** 40, 41, 42, 43, 44, 45

#### What to build

Create insights endpoints:
- GET /insights/stats - Total memories, count by mood, count by tag, avg importance
- GET /insights/trends - Memories per week/month, mood trends over time
- GET /insights/word-cloud - Most frequent words in memories (extract from title+summary)
- GET /insights/achievements - Badges/milestones (e.g., "100 memories," "First story," streak info)

#### Acceptance criteria

- [x] GET /insights/stats returns aggregated memory stats
- [x] GET /insights/trends returns time-series data (memories per period, mood trends)
- [x] GET /insights/word-cloud returns word frequencies
- [x] GET /insights/achievements returns earned badges and progress toward milestones
- [x] Test: Create memories with various moods/tags, verify stats/trends/word-cloud

---

## PHASE 7: Frontend (React/Next.js)

### Issue 19: Build capture UI (voice recorder, text input, form)

**Type:** AFK  
**Blocked by:** Issue 4 (capture API)  
**User stories covered:** 1, 2, 3, 4, 5, 6

#### What to build

Create capture page in React/Next.js:
- Voice recorder (HTML5 audio + visualization)
- Text textarea for direct text input
- Quick form (mood selector, tag input, date picker)
- Real-time transcription display (if using local Whisper)
- Submit button
- Success/error feedback

Components:
- VoiceRecorder (MediaRecorder API, audio visualization)
- TextInput (textarea)
- QuickForm (mood, tags, date)
- CaptureForm (orchestrates inputs)

#### Acceptance criteria

- [x] Voice recorder works (records audio, displays waveform)
- [x] Text input accepts arbitrary text
- [x] Quick form captures mood, tags, optional date
- [x] Submit calls POST /memories/capture
- [x] Success response shows memory created
- [x] Error handling (display errors to user)
- [x] Test: Record voice, submit, verify memory appears in list

> **Status: MOSTLY DONE.** `CapturePanel` supports text/voice/form modes; voice uses `MediaRecorder` → `captureVoice`. No audio waveform visualization, no separate date picker (event date is edited later in `MemoryEditor`), and no live/incremental transcription. Voice submit is transcribed server-side.

---

### Issue 20: Build memory list & search UI

**Type:** AFK  
**Blocked by:** Issue 9 (hybrid search), Issue 19 (capture UI)  
**User stories covered:** 17, 18, 19, 20, 21, 22

#### What to build

Create search/discovery page in React/Next.js:
- Unified search bar (supports text, semantic queries)
- Filter panel (date range, tags, mood, importance slider)
- Results display (cards with title, snippet, relevance score)
- Pagination
- Click to view/edit memory

Components:
- SearchBar (text + semantic input)
- FilterPanel (date picker, tag selector, mood checkboxes, importance slider)
- SearchResults (result cards, pagination)
- MemoryCard (displays title, snippet, relevance score, click to expand)

#### Acceptance criteria

- [ ] Search bar accepts text and semantic queries
- [x] Filter panel works (apply filters, reset)
- [ ] Results display with relevance scores
- [x] Click result to view/edit memory
- [ ] Pagination works
- [ ] Test: Search for memory, apply filters, navigate results

> **Status: PARTIAL.** Search bar + mood/tag/importance filters + click-through work. The bar sends only `text` (no semantic mode toggle), there is no date-range filter and no reset button, results show as `MemoryCard`s without relevance scores, and there is no pagination control. Backend supports all of these — the UI just doesn't expose them yet.

---

### Issue 21: Build memory editor UI (rich text + entity editing)

**Type:** AFK  
**Blocked by:** Issue 12 (edit API), Issue 20 (memory list)  
**User stories covered:** 23, 24, 25, 26, 27

#### What to build

Create memory editor page in React/Next.js:
- Rich text editor for raw_input / structured_content (TipTap, Slate, or similar)
- Inline entity tags (clickable to edit)
- Sidebar showing related memories (RAG links)
- Mood selector
- Importance slider
- Tag editor (add/remove)
- Auto-save on changes

Components:
- RichTextEditor (TipTap/Slate wrapper)
- EntityTags (clickable, inline editable)
- RelatedMemories (sidebar with links)
- MoodSelector
- ImportanceSlider
- TagEditor

#### Acceptance criteria

- [ ] Rich text editor works (format text, save to backend)
- [ ] Entity tags are clickable and editable
- [ ] Related memories sidebar displays
- [x] Mood/importance/tags editable
- [ ] Auto-save to backend
- [x] Test: Edit memory, verify changes persist

> **Status: PARTIAL.** `MemoryEditor` provides a plain form (title, text, mood, location, event date, tags, people, importance) with an explicit Save button. No rich-text editor, no inline entity tags, no related-memories sidebar, and no auto-save/debounce.

---

### Issue 22: Build timeline view (chronological browsing)

**Type:** AFK  
**Blocked by:** Issue 17 (timeline API), Issue 20 (memory list UI)  
**User stories covered:** 28, 29, 30, 31

#### What to build

Create timeline page in React/Next.js:
- Chronological display of memories (vertical or horizontal timeline)
- Date picker/range selector
- Filter by tags/mood
- Cards show memory date + title + snippet
- Click to expand/edit

Components:
- Timeline (vertical/horizontal list)
- TimelineCard (memory entry with date, title, snippet)
- DateRangeSelector
- FilterPanel (tags, mood)

#### Acceptance criteria

- [x] Timeline displays memories chronologically
- [ ] Date range selector filters timeline
- [ ] Tag/mood filters work
- [x] Click memory to view/edit
- [x] Visual engagement (cards, spacing, dates)
- [ ] Test: View timeline, filter by date/tag, click memory

> **Status: PARTIAL.** Chronological, date-grouped timeline with click-through works (uses `/api/timeline`). No date-range selector and no tag/mood filter controls in the UI, though the endpoint supports them.

---

### Issue 23: Build story builder & viewer UI

**Type:** AFK  
**Blocked by:** Issue 15 (story generation API), Issue 20 (memory list)  
**User stories covered:** 32, 33, 34, 35, 36, 37, 38, 39

#### What to build

Create story builder page in React/Next.js:
- Memory selection (checkboxes to choose memories)
- Story type selector (chronological, thematic, curated, digest)
- Custom prompt textarea (optional)
- Generate button (calls API, shows loading state)
- Generated narrative viewer (markdown rendered)
- Export button (markdown, PDF, txt)

Components:
- MemorySelector (list with checkboxes)
- StoryTypeSelector (radio buttons)
- CustomPromptInput (textarea)
- GenerateButton (with loading)
- NarrativeViewer (renders markdown)
- ExportButton (format selector)

#### Acceptance criteria

- [x] Can select memories from list
- [x] Story type selector works
- [x] Custom prompt optional input
- [x] Generate button calls API
- [x] Loading state while generating
- [x] Narrative displays (markdown rendered)
- [x] Export works (at least markdown)
- [x] Test: Select memories, generate chronological story, export to markdown

> **Status: DONE.** Story list, selection, type selector, custom prompt, loading state, and markdown/txt/json export all present. Narrative is rendered in a monospace block rather than rich markdown (minor polish).

---

### Issue 24: Build insights/fun area UI (stats, trends, badges)

**Type:** AFK  
**Blocked by:** Issue 18 (insights API)  
**User stories covered:** 40, 41, 42, 43, 44, 45

#### What to build

Create insights dashboard page in React/Next.js:
- Stats cards (total memories, by mood, by tag, avg importance)
- Trends chart (memories per week, mood timeline)
- Word cloud visualization (most frequent words)
- Badges/achievements gallery (earned badges, progress bars for upcoming)
- Daily streak counter

Components:
- StatsCard (displays metric)
- TrendsChart (line/bar chart of time-series data)
- WordCloud (visualization of word frequencies)
- BadgeGallery (earned badges, progress toward next)
- StreakCounter

#### Acceptance criteria

- [x] Stats cards display correctly
- [x] Trends chart visualizes data
- [x] Word cloud displays frequencies
- [x] Badge gallery shows achievements
- [ ] Streak counter updates daily
- [x] Visual polish (colors, spacing, engagement)
- [ ] Test: Check stats, verify counts match actual memories

> **Status: MOSTLY DONE.** Stats cards, weekly trends bar chart, mood pie chart, top-tags chart, word cloud, and achievements with progress bars are all wired to Issues 18 endpoints. No streak counter (`streak_days` exists on the schema but isn't rendered).

---

### Issue 25: Build navigation & auth UI (layout, login, signup)

**Type:** AFK  
**Blocked by:** Issue 3 (auth API)  
**User stories covered:** 46, 47, 48

#### What to build

Create core layout and auth pages:
- Login page (username/email, password)
- Signup page (username, email, password, confirm password)
- Navigation bar/sidebar (links to capture, search, timeline, stories, insights)
- User profile menu (logout, settings)
- Protected routes (redirect to login if not authenticated)

Components:
- LoginForm
- SignupForm
- NavigationBar
- ProtectedRoute (higher-order component)
- UserMenu

#### Acceptance criteria

- [x] Login page works (calls auth API, stores JWT)
- [x] Signup page works (creates account, auto-logs in)
- [x] Navigation bar displays, links work
- [x] Logout button works (clears JWT, redirects to login)
- [x] Protected routes redirect unauthenticated users to login
- [x] JWT stored in localStorage/cookies
- [x] Test: Signup, login, navigate between pages, logout

---

## PHASE 8: Deployment & Polish

### Issue 26: Set up APScheduler for async agent jobs

**Type:** AFK  
**Blocked by:** Issue 2 (FastAPI), Issue 6 (Refinement), Issue 8 (Enrichment)  
**User stories covered:** 11, 12

#### What to build

Integrate APScheduler into FastAPI:
- Job scheduler runs refinement/enrichment agents asynchronously
- Jobs triggered after memory capture
- Job status tracked in job_status table
- Error handling & retries

Configuration:
- Scheduler persistence (database-backed)
- Job timeouts (refinement 5s, enrichment 10s, story 30s)
- Error logging & alerting

#### Acceptance criteria

- [x] APScheduler integrated into FastAPI
- [x] Refinement job triggered after capture, runs async
- [x] Enrichment job triggered after refinement, runs async
- [x] Job status tracked in DB
- [x] Error handling (log errors, don't crash)
- [x] Test: Capture memory, verify refinement/enrichment run async

> **Status: DONE (simplified).** `AsyncIOScheduler` starts in the FastAPI lifespan; refinement/enrichment are chained via `DateTrigger` and tracked in `job_status`. Simplified vs. plan: no persistent job store (in-memory), no explicit per-job timeouts, no retry policy. `misfire_grace_time=60` is set.

---

### Issue 27: Deploy to Render (FastAPI service + Postgres)

**Type:** AFK  
**Blocked by:** Issue 1 (Postgres DB), Issue 2 (FastAPI), Issue 26 (async jobs)  
**User stories covered:** All (deployment)

#### What to build

Deploy complete MEMIND application to Render:
- FastAPI service on Render (web service)
- PostgreSQL instance (from Issue 1)
- Environment variables configured (DATABASE_URL, OLLAMA_API_KEY, etc.)
- Build/start commands set up
- Logs accessible
- Health check endpoint configured

Documentation:
- Deployment guide
- Environment variables list
- Database migrations
- Running locally vs. on Render

#### Acceptance criteria

- [ ] FastAPI service deployed to Render
- [ ] PostgreSQL connected
- [ ] Environment variables configured
- [ ] Health check endpoint (GET /health) works
- [ ] Can make API calls to deployed service
- [ ] Logs visible in Render dashboard
- [ ] Test: Hit deployed API, create memory, search

---

## PHASE 9: Tellings (Repeated Recall → Many Memories)

Multi-memory capture: one recounting becomes many memories.

**Design:** `docs/TELLING_MODEL.md` — schema, cursor algorithm, privacy and the
rejected alternatives.
**PRD:** the problem, solution and 30 user stories this was sliced from are
preserved at commit `ed49d79` (they were replaced here by the issues below).
**Triage:** every issue is `ready-for-agent` except Issue 29, which is HITL and
needs human judgement before it can be called done.

These are tracer bullets. Each cuts through schema, API, UI and tests, and is
demoable on its own.

---

### Issue 28: Tell a story and get one memory

**Type:** AFK
**Blocked by:** None - can start immediately
**User stories covered:** 2, 5, 10, 11, 17, 18, 19, 22, 23

#### What to build

The thinnest end-to-end path for a Telling. A user types a long account, the
system proposes it as a single segment, the user reviews it and commits, and one
real Memory results, linked back to the telling it came from.

Introduce the `tellings` and `telling_segments` tables. Segments are drafts and
must never be rows in `memories` — this is the central decision of the design,
and this slice exists mainly to establish and prove it.

The splitter in this slice is deliberately trivial: one segment covering the
whole transcript. It is not throwaway scaffolding — it becomes the permanent
fallback used whenever segmentation fails.

Commit must create memories through the existing entity-sync and review-flag
helpers, so entities, review flags and privacy behave exactly as in a normal
capture. Commit must **not** re-run the Capture Agent: the segment's reviewed
content is authoritative, and re-structuring each segment in isolation would
destroy the narrative context segmentation recovered.

Surfaces: submit a typed telling, fetch it with its segments, edit a segment's
text/title/summary and accept or reject it, and commit; plus a "tell a story"
mode on the capture surface and a review screen.

#### Acceptance criteria

- [x] Submitting a typed telling stores the transcript and returns the telling
      with one proposed segment
- [x] Tellings and segments live in their own tables and are never rows in
      `memories` before commit
- [x] A segment's text, title and summary can be edited before commit
- [x] Committing creates one memory per accepted segment, each linked back to
      its telling
- [x] Committed memories sync entities and apply review flags identically to a
      normal capture
- [x] Commit does not re-run the Capture Agent
- [x] Before commit, no memory, timeline, review-queue or search response
      mentions the telling, and no entity count changes
- [x] A telling is visible only to its owner
- [x] Tests cover the commit path and the draft-isolation invariant

> **Status: DONE.** Deployed and verified live. Twelve backend tests
> (`tests/test_tellings.py`) and eleven frontend tests cover the four
> endpoints, the commit path, and the draft-isolation invariant — including a
> companion test proving that invariant is not vacuous. Two extras beyond the
> brief: an unknown segment status is rejected with a 400, and a second commit
> is refused with a 409.
>
> Deviations: the capture mode is a sibling of `CapturePanel` on the capture
> page rather than a fourth mode inside it, which avoided modifying working
> code with no tests. The client-level tests passed as soon as they were
> written, since the methods already existed by then; they are kept as guards
> against URL drift.

---

### Issue 29: Split a telling into memories

**Type:** HITL
**Blocked by:** Issue 28
**User stories covered:** 4, 5, 30

#### What to build

Replace the single-segment splitter with real segmentation: one model pass over
the whole transcript producing an ordered list of segments, each carrying its
verbatim transcript text and the usual structured fields.

Return verbatim span text rather than character offsets — models miscount
offsets, and the full transcript is retained as the source of truth. Do not
depend on sentence boundaries or punctuation; the output must cope with an
unpunctuated ramble, because the primary input is speech. Normalise each segment
through the same validation the single-memory capture path already uses. If the
model is unreachable or returns nothing usable, fall back to the single-segment
splitter from Issue 28 rather than losing the user's words.

**This slice is HITL.** Segmentation quality cannot be asserted by a test: it
must be judged against one real, rambling recording. The slice is not done until
a human has listened to a genuine recording and agreed the split is usable.

#### Acceptance criteria

- [x] One model pass produces an ordered list of segments from a transcript
- [x] Each segment carries verbatim transcript text, not offsets
- [x] Segments are normalised through the existing single-memory validation
- [x] Segmentation works on a transcript with no paragraph breaks and
      unreliable punctuation
- [x] A failing or unusable model falls back to one segment covering the whole
      transcript
- [x] The review screen shows the multiple proposed memories
- [x] A human has validated the split against a real recording

> **Status: DONE.** Validated against two real accounts, the second written
> deliberately non-linear and self-correcting; the split held, and the account
> was not duplicated even though it described the same event twice.
>
> Two problems surfaced only under real accounts, both cases of the model
> over-helping, and both now guarded:
>
> - a year mentioned in passing ("the DJ played early 2000s throwbacks") was
>   being used as the memory's date. The prompt forbids incidental dates, and
>   an explicit null from the segmenter now beats the deterministic scan in
>   `_build_structured_memory`, which would otherwise put the year straight back
> - a day and month with no year ("August 15th") came back as `1900-08-15`
>   marked `exact`. Exact dates whose year never appears in the segment text
>   are now dropped; only exact dates are policed, since a decade or range is
>   an honestly fuzzy answer
>
> Known and accepted: the model occasionally inserts a missing space while
> copying a span (Whisper output has them). One character in ~1800, meaning
> unchanged, judged not worth chasing.
>
> The web UI gains a Story tab on the capture surface as part of this work.

---

### Issue 30: Dates resolve within the story

**Type:** AFK
**Blocked by:** Issue 29
**User stories covered:** 12, 14, 15

#### What to build

Resolve dates against the narrative rather than against today. Split date
resolution into two responsibilities: an absolute resolver (explicit dates,
fuzzy periods, named life periods) and a relative-offset resolver ("the next
day", "two years later", "the week before").

Thread a cursor through the ordered segments. An absolute date resets it; a
relative phrase computes off it and moves it forward. A jump in time is handled
for free, because an absolute date re-anchors everything that follows.

Precision may coarsen but must never sharpen: "1985" plus "two years later" is
still year-precision, not a moment. The resolved date is shown in the review
screen and stays manually correctable.

#### Acceptance criteria

- [x] Absolute dates reset the cursor; relative phrases compute from it
- [x] "The next day" resolves relative to the preceding event, not to today
- [x] Shifting a fuzzy date never sharpens its precision
- [x] Backwards references work
- [x] A leap to a new absolute date re-anchors subsequent relative phrases
- [x] The resolved date is visible and editable in the review screen
- [x] The committed memory carries the narrative-resolved date

> **Status: DONE.** Verified on live input: "In August 2003…" anchors at
> 2003-08-01, "The next day" resolves to 2003-08-02, and "Two years later" to
> 2005 at year precision.
>
> Three things only real input revealed, none of which a unit test would have
> predicted:
>
> - the cursor was being *bypassed*: the segmenter supplied a date of its own
>   for "The next day" (the nearest month it could see), and a supplied date
>   won, so the phrase was never resolved. Relative phrases now take precedence
> - "no date" from the segmenter means two different things. Shown "The next
>   day" alone it genuinely cannot resolve it — that is the cursor's job. But
>   for "the DJ played early 2000s throwbacks" it correctly refuses, and the
>   cursor was putting the year straight back. Only the first is handed on
> - a label outlived its period: "two years later" carried "August 2003" onto
>   a 2005 date. A label now survives a shift only while the result stays
>   inside the period it describes
>
> Month and year arithmetic is calendar-aware — five years after 1976-07-29 is
> 1981-07-29, and a fixed 365-day year lands on the 28th, which the test caught.
>
> Note for Issue 31: a leading "the next day" with no prior anchor stays
> deliberately undated. Deciding what a story-wide frame should supply is that
> issue's job, not this one's.

---

### Issue 31: A story-wide period for undated parts

**Type:** AFK
**Blocked by:** Issue 30
**User stories covered:** 13, 16

#### What to build

Give the telling its own frame date and label ("high school", "the summer of
1985"). Segments with no date signal of their own inherit that frame as a fuzzy
label instead of being queued for review.

This turns what is currently a failure mode into a good outcome: a story about a
period of life yields dated memories rather than a pile of undated ones.

A segment reaches the review queue only when the telling has no frame either —
genuinely no signal at all anywhere.

#### Acceptance criteria

- [x] A telling can carry a frame date and label
- [x] Undated segments inherit the telling's frame as a date label
- [x] Inherited segments are not queued for review
- [x] A segment with no signal and no telling frame is still queued for review
- [x] Committed memories carry the inherited label, and the timeline groups
      them accordingly

> **Status: DONE.** Verified live: the non-linear account yields frame
> "first month in high school", carried by all four segments. Its frame_date is
> null, and honestly so — that account never states a year.
>
> The frame is *derived* rather than asked for: the segmenter already applies a
> period's wording to every memory it covers, so the label the segments most
> share is the frame. That needed no prompt change, and it handles the case
> actually observed, where one segment came back unlabelled while the rest
> shared a period — derivation still finds the frame and the odd one inherits it.
>
> Ordering matters and is deliberate: the cursor runs first and the frame
> second, so a precise answer always beats a vague one. Only what is still
> undated inherits.
>
> The review-queue and timeline criteria needed no new logic — `apply_review_flags`
> already counts a label as a time signal, and `commit_telling` already copies
> the label onto the memory. Both are now pinned by tests rather than assumed.
>
> `segment_transcript` returns a `SegmentationResult` carrying the frame beside
> the segments, since a frame belongs to the telling and not to any one memory.
> The fallback path is dated the same way, so a model outage costs the split but
> not the dates.
>
> Not claimed: a `frame_date` on a period-of-life telling that never states a
> year. There is no honest value for it, and inventing one is the bug Issue 29
> already fixed once.

---

### Issue 32: Reshape the split

**Type:** AFK
**Blocked by:** Issue 29
**User stories covered:** 6, 7, 8, 9

#### What to build

Let the user correct a proposed split before committing: merge two adjacent
segments, split one in two, delete a segment, and reorder them.

Structural edits operate on the draft only. Nothing reaches `memories` until
commit.

#### Acceptance criteria

- [x] Two adjacent segments can be merged into one
- [x] A segment can be split into two
- [x] A segment can be deleted from the draft
- [x] Segments can be reordered
- [x] Ordinals remain consistent after every structural edit
- [x] Each edit is reflected in the review screen without a full reload

> **Status: DONE.** Each operation is its own endpoint rather than one generic
> "update segments" call, so the intent is legible in the API.
>
> Two decisions worth keeping: merging keeps the *first* segment's structured
> content and splitting leaves the new half blank, both because the text has
> changed and carrying the old title or date over would describe words the
> segment no longer contains. Re-deriving it would mean another model call,
> which is not what a structural edit should cost.
>
> Structural edits are refused with 409 once a telling is committed — its
> segments are memories by then, so moving their boundaries would orphan them.
> Issue 33's undo, or Issue 34's re-split, are the routes out of that state.
>
> A bug found on the way: re-querying a telling returned the identity-mapped
> object whose segment collection was whatever loaded last, so a merge looked
> like it had done nothing. `_load_telling` now forces a rebuild from the rows.

---

### Issue 33: Provenance and undo

**Type:** AFK
**Blocked by:** Issue 28
**User stories covered:** 18, 19, 21, 26

#### What to build

Make a committed telling's provenance usable: see every memory it produced, and
delete the whole batch in one action so a bad commit is reversible. The telling
and its transcript survive, so it can be re-split afterwards.

#### Acceptance criteria

- [x] Every committed memory links to the telling that produced it
- [x] All memories from one telling can be listed
- [x] The whole batch can be deleted in one action
- [x] Deleting the batch does not delete the telling or its transcript
- [x] A memory from a telling can be marked private like any other

> **Status: DONE.** The link the schema already had (`telling_segments.memory_id`,
> set by `commit_telling` since Issue 28) is now usable rather than merely
> recorded.
>
> Deleting the batch clears the links and returns the telling to `draft`, so a
> bad commit is a step back rather than a loss — the transcript and every
> segment's text and date survive, and the same telling can be committed again.
> A test commits, deletes and re-commits to prove it.
>
> The listing reuses the memories route's own response builder rather than a
> second one, so a private memory cannot leak through this path. Worth knowing
> because a second builder is exactly where that rule would get forgotten.
>
> Not addressed: deleting memories leaves `entities.mention_count` denormalised
> upward. Pre-existing — deleting a memory has always had this — but a batch
> delete makes it easier to notice.

---

### Issue 34: Re-split an edited transcript

**Type:** AFK
**Blocked by:** Issue 29, Issue 32
**User stories covered:** 20

#### What to build

Let the user edit a telling's transcript and re-run segmentation, replacing the
draft segments. Useful when transcription mangled a passage, or when the first
split was simply wrong.

Re-splitting a draft replaces its segments. Re-splitting a committed telling
produces a new draft and leaves the already-committed memories untouched.

The review screen is the place this has to be reachable from. Rejecting
segments is how a user says "this split is wrong", and the loop it should lead
into is *edit the transcript, re-run, review again* — not manually merging,
splitting and deleting segment by segment to reconstruct the account by hand.
When every proposed segment has been rejected, the screen should say plainly
that there is nothing left to commit and offer the way back to the transcript.

#### Acceptance criteria

- [ ] A telling's transcript can be edited
- [ ] Re-running segmentation replaces the existing draft segments
- [ ] Re-splitting a committed telling does not modify its committed memories
- [ ] The user is warned before a re-split discards the current draft
- [ ] After a re-split the user can see what changed: which segments are new,
      which are gone, and which survived with edits
- [ ] The transcript can be edited and re-split from the review screen, without
      leaving it
- [ ] Rejecting every segment leaves the user on a clear path to edit the
      transcript and re-run, rather than stuck on an empty draft

---

### Issue 35: Spoken tellings

**Type:** AFK
**Blocked by:** Issue 28, Issue 29
**User stories covered:** 1, 3, 24, 25, 27, 28, 29

#### What to build

Tell a story out loud. Audio is uploaded, transcribed with the existing local
transcription, and enters the same pipeline as a typed telling.

This slice forces background processing: a long recording cannot block a
request. Transcription and segmentation run in the background using the
existing scheduler and job-status mechanism, and the client polls the telling
until it is ready to review.

If transcription or segmentation fails, the telling and its transcript must
survive so the spoken words are never lost.

#### Acceptance criteria

- [ ] Audio can be uploaded for a telling
- [ ] The recording is transcribed with the existing local transcription
- [ ] Transcription and segmentation run in the background, not inline
- [ ] The client can show progress while a telling is being processed
- [ ] A failed transcription or segmentation leaves the telling and any
      transcript intact
- [ ] A telling can be abandoned before commit
- [ ] A telling is readable only by its owner

---

### Issue 36: Return to a draft telling

**Type:** AFK
**Blocked by:** Issue 28
**User stories covered:** new — raised after using the flow

#### What to build

A telling already persists as a draft from the moment it is created, and
segment edits are saved as they are made. What is missing is any way to *find*
one again. Only `GET /tellings/{id}` exists, so a telling abandoned mid-review
is effectively lost — reachable only if you kept the URL.

Give the user a place to see their uncommitted tellings and reopen one, and
make the capture surface point at it when a draft is waiting. The same list
should show tellings that failed to transcribe or segment, since those hold the
user's words and currently surface nowhere either.

Distinguish clearly between drafts and committed tellings in that list, because
only drafts can be resumed.

#### Acceptance criteria

- [ ] Uncommitted tellings can be listed for the signed-in user
- [ ] A draft can be reopened and resumed exactly where it was left
- [ ] Tellings that failed transcription or segmentation are listed, not hidden
- [ ] Committed tellings are distinguishable from drafts
- [ ] The list is scoped to its owner
- [ ] The capture surface shows when a draft is waiting to be finished

---

## PHASE 10: Account Recovery

### Issue 37: Password reset with a one-time token

**Type:** AFK
**Blocked by:** None
**User stories covered:** new — raised after the operator was locked out

#### What to build

There is no way to recover an account. Auth offers register, login and refresh
only, and the operator of this instance recently had to reset a password by
hand against the database. That is a poor answer for a product whose whole
premise is that your memories live inside it.

Add a reset flow built on a one-time token:

- requesting a reset creates a single-use token, stored **hashed**, with a
  short expiry and a used-at stamp
- delivery is pluggable: if SMTP is configured the link is emailed, otherwise
  it is written to the application log and a supported command prints a
  ready-made link
- following the link lets the user set a new password, which invalidates that
  token and any other outstanding tokens for the account

**The API must never return the token in its response.** The moment it does,
anyone who knows a username — and these usernames are guessable — can take over
the account. "Displayed" means displayed to the operator, never to the caller.

#### Acceptance criteria

- [ ] A reset can be requested by username or email
- [ ] The request answers identically whether or not the account exists, so it
      cannot be used to discover who has an account
- [ ] Tokens are stored hashed, never in plaintext
- [ ] A token is single-use and expires
- [ ] Completing a reset invalidates that token and any others outstanding
- [ ] The token never appears in an HTTP response body
- [ ] With no SMTP configured, the link is written to the log
- [ ] With SMTP configured, the link is emailed instead
- [ ] Reset requests are rate limited per account

#### Notes

Email is the only delivery that works away from the box, but a self-hosted
domain needs SPF/DKIM or the reset lands in spam — worse than no reset at all.
Hence the pluggable design: build the token machinery once, switch email on
when a relay exists. There is no mail code in the project today and no relay on
the host, so the log path is what will actually run first.

---

## PHASE 11: Real-World Enrichment

### Issue 38: Look real-world things up

**Type:** AFK
**Blocked by:** None
**User stories covered:** new — raised while using the app
**Status:** idea only. Brainstorm before this becomes work.

#### What to build

A memory says "we saw a show at Mission Valley Theater in Raleigh". MEMIND
stores an entity called "Mission Valley Theater" and a place "Raleigh", and
does nothing else with them. The theatre closed years ago — which is exactly
the sort of thing a memory system could know, and the user cannot be expected
to.

So the idea: when a memory names a real-world thing, attach something useful —
an address, what the place was, whether it still exists, when it closed. Not
invented prose. Looked-up facts, with a source, held separately from what the
user actually said.

Related: `ENRICHMENT_IDEAS.md` already collects proposals in this area, and the
Enrichment Agent (Issue 8) exists — but it enriches from the user's *other
memories*, not from the outside world. This is the outside world.

#### Open questions to settle first

- lookup source: OpenStreetMap/Overpass, Wikipedia, a geocoder — and how to do
  it without a paid dependency or an API key that expires
- where it lives: on the entity, on the memory, or as a separate attachment so
  it can never pollute the user's own words
- how it is shown without the user mistaking a looked-up fact for their own
  recollection — this matters more than it sounds, on a platform whose value is
  that the memories are *yours*
- what happens when the lookup is wrong, and whether the user can correct it
- whether a closed business is *worth* flagging, or just noise

#### Acceptance criteria

Not written yet. Brainstorm first.

---

## Summary

**Total Issues:** 38  
**Vertical slices:** Organized in 8 build phases (Foundation → Infrastructure → Core Processing → Search → Management → Narrative → Timeline → Deployment), plus **Phase 9 (Tellings)** — Issues 28-36, cut as tracer bullets. Note also that the deployment target is no longer Render: MEMIND now runs on the homelab box behind Traefik and cloudflared at `memory.cloutier.work`, with Postgres.

**Current status (2026-09-22):** 24 of 27 issues done; 3 partial (1, 4, 7) and 1 not started (27).

**Remaining work by area:**
1. **Deploy (Issue 27)** — Render web service + Postgres/pgvector; also unblocks native tsquery/pgvector search.
2. **Voice transcription (Issue 4)** — wire an actual transcription backend; today `_transcribe_audio` returns 501.
3. **Frontend depth (Issues 20–22, 24)** — semantic search mode, date filters, relevance scores, pagination, rich-text/entity editor, related-memories sidebar, autosave, streak counter.
4. **Capture & parsing quality (Issues 4–6)** — active iteration area.
5. **Tellings (Phase 9, Issues 28–36)** — multi-memory capture from a single recounting. Issues 28 and 29 are done; 30 (dates resolving within the story) is nearly done — its cursor works and two UI criteria remain. Issue 35 (spoken tellings) is what makes audio recording work for a story.

6. **Account recovery (Phase 10, Issue 37)** — there is no way back into an account whose password is lost; the operator had to reset one by hand. Not blocking, but the only security-shaped gap outstanding.

**Dependencies:**
- Phase 1 (Foundation) has no blockers
- Phase 2 (Capture) blocked by Phase 1
- Phase 3 (Search) blocked by Phase 2
- Phase 4 (Editing) blocked by Phase 2-3
- Phase 5 (Stories) blocked by Phase 2-4
- Phase 6 (Timeline) blocked by Phase 2-3
- Phase 7 (Frontend) blocked by Phase 1-4
- Phase 8 (Deployment) blocked by all preceding phases
- Phase 9 (Tellings) blocked by the capture path (Issues 4-6), the timeline (17), the capture UI (19) and the scheduler (26) — all of which are done

**Estimated effort:** ~60-80 developer hours for MVP (Phase 1-6 complete)

**Phase 9 estimate:** the date cursor and segmenter are self-contained (roughly a day each with tests); schema, endpoints, commit path and the review UI are the bulk of the work.

