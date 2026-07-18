# MEMIND Issues - Vertical Slices

## PHASE 1: Foundation & Infrastructure

### Issue 1: Set up Postgres with pgvector on Render

**Type:** AFK (but requires Render account interaction)  
**Blocked by:** None - can start immediately  
**User stories covered:** All (foundational)

#### What to build

Create a PostgreSQL 15+ instance on Render with the pgvector extension enabled. Configure connection pooling and create the base schema including `users`, `memories`, `entities`, `stories` tables with proper indexes. Verify pgvector is installed and operational with a test embedding insert.

#### Acceptance criteria

- [ ] PostgreSQL 15+ instance created on Render
- [ ] pgvector extension installed and enabled
- [ ] Base schema created (users, memories, entities, stories tables)
- [ ] Proper indexes created for performance (user_id, created_at, tags GIN, embedding ivfflat)
- [ ] Connection string available (DATABASE_URL env var documented)
- [ ] Test: Insert a test memory with embedding and query it via pgvector

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

- [ ] FastAPI project initialized with proper directory structure
- [ ] All Pydantic models defined and tested for validation
- [ ] Database connection established (async SQLAlchemy)
- [ ] Environment variable loading (python-dotenv or Pydantic settings)
- [ ] Logging configured
- [ ] README with setup instructions (poetry install, env vars, run)
- [ ] Test: Can import all models and validate basic data shapes

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

- [ ] POST /auth/register endpoint works (creates user, returns JWT)
- [ ] POST /auth/login endpoint works (validates password, returns JWT)
- [ ] JWT tokens contain user_id claim and expire correctly
- [ ] POST /auth/refresh endpoint extends session
- [ ] Auth middleware extracts user_id from token
- [ ] get_current_user() dependency works in protected routes
- [ ] Test: Can register, login, and access protected routes; cannot access other user's data

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

- [ ] POST /memories/capture accepts voice (audio file), text, and form data
- [ ] Multipart form data handling works
- [ ] Voice transcription via Ollama Whisper works
- [ ] Memory created in DB with state='raw'
- [ ] User sees response immediately (state='raw')
- [ ] Async refinement job scheduled in background
- [ ] Test: Can capture voice/text, get immediate response, verify DB state

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

- [ ] Capture Agent calls Ollama API with correct prompt
- [ ] Response parsed into StructuredMemory Pydantic model
- [ ] Validation ensures all required fields present
- [ ] Returns within ~1 second
- [ ] Handles Ollama API errors gracefully (fallback response)
- [ ] Test: Feed rambling text, get structured JSON with title/summary/entities

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

- [ ] Refinement Agent scheduled async after capture
- [ ] Calls Ollama with prompt including similar memories
- [ ] Resolves ambiguous references (vague pronouns, implicit references)
- [ ] Normalizes dates (various formats → ISO 8601)
- [ ] Updates memory state to 'refined'
- [ ] Completes in ~2-3 seconds
- [ ] Handles errors without crashing
- [ ] Test: Capture with vague reference ("that meeting"), verify refinement resolves it

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

- [ ] Ollama embeddings API integration works (generate_embedding function)
- [ ] Embeddings stored in pgvector column (correct dimension)
- [ ] Similarity search function returns top-K most similar memories
- [ ] Queries by cosine distance (pgvector similarity)
- [ ] Test: Insert memory with embedding, query by semantic similarity, verify results

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

- [ ] Generates embedding via Ollama embeddings API
- [ ] Retrieves top-5 similar memories from pgvector
- [ ] Calls Ollama Chat API with context from similar memories
- [ ] Suggests tags, importance level, related memory links
- [ ] Updates memory state to 'enriched'
- [ ] Completes in ~3-5 seconds
- [ ] Test: Enrich a memory, verify tags/importance/related links are reasonable

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

- [ ] POST /memories/search endpoint accepts text, semantic, filters
- [ ] Full-text search via PostgreSQL tsquery works
- [ ] Semantic search via pgvector works
- [ ] Structured filters (date, tags, mood, importance) work
- [ ] Results ranked by combined relevance score
- [ ] Pagination supported (limit, offset)
- [ ] Returns within ~1 second (including semantic search)
- [ ] Test: Search by text ("coffee"), semantic ("casual meetings"), filters (mood=happy), combinations

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

- [ ] Parses natural language to structured SearchQuery
- [ ] Extracts text keywords, semantic intent, filters
- [ ] Handles time expressions ("Q1", "last month", "this week")
- [ ] Integrates with hybrid search from Issue 9
- [ ] Test: Query "manager conversations in Q1", verify parsed correctly and returns results

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

- [ ] GET /memories/:id returns full MemoryResponse
- [ ] GET /memories returns paginated list of user's memories
- [ ] Pagination supports limit, offset, sort
- [ ] 404 if memory doesn't exist or belongs to different user
- [ ] Test: Create memory, retrieve by ID, list memories

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

- [ ] PATCH /memories/:id accepts partial updates
- [ ] Can update title, summary, entities, mood, tags, importance
- [ ] Pydantic validation on updates
- [ ] 404 if memory doesn't exist or belongs to different user
- [ ] Updated_at timestamp updated
- [ ] Test: Edit memory, verify changes persist

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

- [ ] DELETE /memories/:id removes memory and associated records
- [ ] Cascade delete for entities
- [ ] 404 if memory doesn't exist or belongs to different user
- [ ] Test: Delete memory, verify it's gone from DB

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

- [ ] Story Agent calls Ollama Chat API with story prompts
- [ ] Generates coherent narrative (tested manually)
- [ ] Supports all 4 story types
- [ ] Falls back to Claude Opus if configured/needed
- [ ] Handles custom prompts (user-provided tone/focus)
- [ ] Returns markdown narrative
- [ ] Test: Generate chronological story from 3 memories, verify narrative makes sense

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

- [ ] POST /stories/generate accepts StoryGenerate
- [ ] Validates memory ownership
- [ ] Calls Story Agent
- [ ] Creates story record in DB
- [ ] Returns StoryResponse with narrative
- [ ] Test: Generate story from memories, verify it's stored

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

- [ ] GET /stories/:id returns full StoryResponse
- [ ] GET /stories returns user's stories paginated
- [ ] POST /stories/:id/export supports markdown, txt, json formats
- [ ] 404 if story doesn't exist or belongs to different user
- [ ] Test: Generate story, retrieve it, export to markdown

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

- [ ] GET /timeline returns memories chronologically ordered
- [ ] Supports date range filtering (start_date, end_date)
- [ ] Supports tag/mood filters
- [ ] Pagination (limit, offset)
- [ ] Test: Retrieve timeline for date range, verify chronological order

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

- [ ] GET /insights/stats returns aggregated memory stats
- [ ] GET /insights/trends returns time-series data (memories per period, mood trends)
- [ ] GET /insights/word-cloud returns word frequencies
- [ ] GET /insights/achievements returns earned badges and progress toward milestones
- [ ] Test: Create memories with various moods/tags, verify stats/trends/word-cloud

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

- [ ] Voice recorder works (records audio, displays waveform)
- [ ] Text input accepts arbitrary text
- [ ] Quick form captures mood, tags, optional date
- [ ] Submit calls POST /memories/capture
- [ ] Success response shows memory created
- [ ] Error handling (display errors to user)
- [ ] Test: Record voice, submit, verify memory appears in list

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
- [ ] Filter panel works (apply filters, reset)
- [ ] Results display with relevance scores
- [ ] Click result to view/edit memory
- [ ] Pagination works
- [ ] Test: Search for memory, apply filters, navigate results

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
- [ ] Mood/importance/tags editable
- [ ] Auto-save to backend
- [ ] Test: Edit memory, verify changes persist

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

- [ ] Timeline displays memories chronologically
- [ ] Date range selector filters timeline
- [ ] Tag/mood filters work
- [ ] Click memory to view/edit
- [ ] Visual engagement (cards, spacing, dates)
- [ ] Test: View timeline, filter by date/tag, click memory

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

- [ ] Can select memories from list
- [ ] Story type selector works
- [ ] Custom prompt optional input
- [ ] Generate button calls API
- [ ] Loading state while generating
- [ ] Narrative displays (markdown rendered)
- [ ] Export works (at least markdown)
- [ ] Test: Select memories, generate chronological story, export to markdown

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

- [ ] Stats cards display correctly
- [ ] Trends chart visualizes data
- [ ] Word cloud displays frequencies
- [ ] Badge gallery shows achievements
- [ ] Streak counter updates daily
- [ ] Visual polish (colors, spacing, engagement)
- [ ] Test: Check stats, verify counts match actual memories

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

- [ ] Login page works (calls auth API, stores JWT)
- [ ] Signup page works (creates account, auto-logs in)
- [ ] Navigation bar displays, links work
- [ ] Logout button works (clears JWT, redirects to login)
- [ ] Protected routes redirect unauthenticated users to login
- [ ] JWT stored in localStorage/cookies
- [ ] Test: Signup, login, navigate between pages, logout

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

- [ ] APScheduler integrated into FastAPI
- [ ] Refinement job triggered after capture, runs async
- [ ] Enrichment job triggered after refinement, runs async
- [ ] Job status tracked in DB
- [ ] Error handling (log errors, don't crash)
- [ ] Test: Capture memory, verify refinement/enrichment run async

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

## Summary

**Total Issues:** 27  
**Vertical slices:** Organized in 8 phases (Foundation → Infrastructure → Core Processing → Search → Management → Narrative → Timeline → Deployment)

**Dependencies:**
- Phase 1 (Foundation) has no blockers
- Phase 2 (Capture) blocked by Phase 1
- Phase 3 (Search) blocked by Phase 2
- Phase 4 (Editing) blocked by Phase 2-3
- Phase 5 (Stories) blocked by Phase 2-4
- Phase 6 (Timeline) blocked by Phase 2-3
- Phase 7 (Frontend) blocked by Phase 1-4
- Phase 8 (Deployment) blocked by all preceding phases

**Estimated effort:** ~60-80 developer hours for MVP (Phase 1-6 complete)

