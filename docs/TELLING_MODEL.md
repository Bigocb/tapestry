# Telling Model — One Recounting, Many Memories

**Status:** Design (approved) · **Related:** `docs/ENTITY_MODEL.md`

## Problem

Capture is strictly **1 input → 1 memory**. `structure_memory()`
(`app/agents/capture.py`) returns exactly one `StructuredMemory`, and
`_structure_and_update_memory()` (`app/routes/memories.py`) writes exactly one
row. But people do not recount memories one at a time. They sit down and
*tell a story*:

> "So in the summer of 1985 we drove down to Florida. **The next day** we went
> to Disney. That was the trip where Dad backed the car into a palm tree. Oh,
> and **two years later** I started college and met Dave."

That is four or five memories. Two things break if you capture it as one:

- **Segmentation.** There is no notion of where one memory ends and the next
  begins.
- **Narrative context.** `resolve_date()` anchors every relative phrase to
  *today*. "The next day" resolves to tomorrow, and "two years later" is
  meaningless. Dates in a narrative are relative to *earlier in the same
  telling*, not to the moment of capture.

## Core idea: separate the recounting from the memories

| Concept | Meaning | Cardinality |
|---|---|---|
| **Telling** | One act of recounting; owns the transcript | One per capture |
| **TellingSegment** | One *proposed* memory, reviewable | Many per telling |
| **Memory** | A real memory; created only at commit | Many per telling |

A `TellingSegment` is **not** a memory and never enters the `memories` table
until the user commits it. Drafts are a separate concept with a separate
lifetime.

### Why drafts are not just flagged memories

The tempting shortcut is `memories.is_draft`, so commit is a flag flip. It is
rejected because **every existing read path would need to learn to exclude
drafts** — list, timeline, review queue, search, insights, `/related` — and
worse, `sync_memory_entities()` would mint real `Entity` rows and increment
`mention_count` from a split the user may discard. That pollutes the entity
graph. This is the same class of leak already fought twice (review flags,
privacy redaction); it is avoided by keeping drafts out of `memories` entirely.

## Naming

`Story` is already taken and means the **opposite thing**: a narrative
*generated from* selected memories (`app/agents/story.py`). A **Telling** is
the input direction — a recounting *that produces* memories. The two must not
share a name, or querying "stories" becomes ambiguous.

- *Telling* — a recounting. "Tell me about it."
- *Transcript* — the raw text (from Whisper or typed).
- *Segment* — a proposed memory cut from the transcript.
- *Commit* — turning accepted segments into real memories.

## Schema

### `tellings` — the recounting

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users, CASCADE | user-scoped like everything else |
| `raw_transcript` | Text | Whisper output or typed text; source of truth |
| `input_type` | String(20) | `voice` \| `text` |
| `status` | String(20) | `transcribing` \| `segmenting` \| `draft` \| `committed` \| `failed` |
| `error` | Text NULL | populated when `status = 'failed'` |
| `frame_date` | TIMESTAMP NULL | telling-wide fallback anchor |
| `frame_label` | String(120) NULL | telling-wide fuzzy label, e.g. "High school" |
| `created_at`, `updated_at` | TIMESTAMP | |

Index: `(user_id, status)`, `(user_id, created_at)`.

### `telling_segments` — the proposed memories

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `telling_id` | UUID FK → tellings, CASCADE | |
| `user_id` | UUID FK → users, CASCADE | denormalized for scoping |
| `ordinal` | Integer | position in the narrative |
| `text` | Text | verbatim span of the transcript |
| `structured_content` | DBJSON | same shape as `memories.structured_content` |
| `event_date`, `date_precision`, `event_date_end`, `date_label` | | resolved by the date cursor |
| `status` | String(20) | `proposed` \| `accepted` \| `rejected` |
| `memory_id` | UUID FK → memories NULL | set on commit |
| `created_at`, `updated_at` | TIMESTAMP | |

Indexes: `(telling_id, ordinal)`, `(user_id)`, `(memory_id)`.

**Audio is not stored.** The transcript is the durable artefact: re-splitting
only needs text. Audio is transcribed and discarded, exactly as the current
single-memory voice path does.

## The date cursor

The core new logic, and the part to build and test first — it is pure,
deterministic, and valuable even if segmentation changes later.

`resolve_date()` currently conflates two jobs. A telling needs them apart:

| Function | Handles | Effect on cursor |
|---|---|---|
| `absolute_date(text)` | "July 29 1976", "summer of 1985", "the 80s", "middle school" | **resets** |
| `relative_offset(text)` | "the next day", "two years later", "the week before" | computed **from** the cursor |

```
cursor = telling frame            # e.g. "High school", ~1988
for segment in segments:
    if absolute := absolute_date(segment.text):
        cursor = absolute                       # absolute always wins
    elif offset := relative_offset(segment.text):
        cursor = shift(cursor, offset)          # moves the cursor forward
    segment.date = cursor or unknown

    if segment.date is unknown:
        segment.date_label = telling.frame_label   # inherit, don't fail
```

Two rules that must be decided correctly:

- **Precision coarsens, never sharpens.** "1985" plus "two years later" is
  still a year, not an instant. `shift()` preserves or degrades precision; it
  never produces `exact` from a fuzzy base.
- **The telling frame is a real answer.** A telling about "high school" gives
  every otherwise-undated segment a `date_label`, which is far better than the
  current outcome (no date ⇒ `needs_review`). Segments only reach the review
  queue when there is genuinely no signal at all.

Backwards references ("the week before") use a negative offset and work
symmetrically. A narrative that jumps around in time is handled for free: an
absolute date resets the cursor, so relative phrases after the jump anchor to
the new point.

## Segmentation

A single LLM pass over the whole transcript returns an **ordered list of
segments**, each with its verbatim text plus the usual structured fields. One
pass matters because the model sees the whole arc, so it can resolve pronouns
("Dave" in segment 1, "he" in segment 4) and carry the date cursor.

Rules:

- **Return verbatim span text, not character offsets.** Models miscount
  offsets. Exact partitioning is unnecessary because `raw_transcript` remains
  the source of truth on the telling.
- **Do not rely on sentence boundaries.** The primary input is speech;
  Whisper output has no paragraphs and unreliable punctuation. Segmentation
  must work on an unpunctuated ramble.
- **Normalise once, at segmentation.** Segment output is validated through the
  same `_build_structured_memory` path as single capture (`_normalize_entities`,
  field clamping), then stored on the segment.
- **Fall back deterministically.** If the LLM is unreachable or returns
  nothing usable, fall back to a single segment covering the whole transcript —
  never lose the user's words.

## Pipeline and status lifecycle

```
POST /tellings            ──► tellings row, status = transcribing
  (text)  immediate       │
  (voice) Whisper         │
                          ▼
                     status = segmenting
                          │  segment pass + date cursor
                          ▼
                     status = draft            ──► segments visible, reviewable
                          │  user reviews, then POST /tellings/{id}/commit
                          ▼
                     status = committed        ──► memories created, memory_id linked
```

Transcription and segmentation run in the background (the existing
APScheduler + `job_status` pattern); the client polls `GET /tellings/{id}`
until `draft`.

## Review and commit

The review UI is the largest new surface. Actions: **edit** a segment's text
and fields, **merge** adjacent segments, **split** one, **delete**, and
**reorder**.

**Commit does not re-run the Capture Agent.** The segment's reviewed
structured content is authoritative: re-structuring each segment *in isolation*
at commit time would throw away exactly the narrative context that
segmentation worked to recover. Instead commit:

1. Creates a `Memory` per accepted segment (`_create_memory`-equivalent).
2. Writes the segment's reviewed `structured_content` and date fields directly.
3. Calls `sync_memory_entities()` and `_apply_review_flags()` — the normal
   write path, so entities, review flags and privacy behave identically to a
   single capture.
4. Links `telling_segments.memory_id` and sets `tellings.status = 'committed'`.

Deleting a telling that has been committed leaves the memories, but the commit
is reversible: the `memory_id` links allow all memories from one telling to be
deleted as a batch, and the transcript is still there to re-split.

## Privacy

Tellings are user-scoped only. The transcript renders nowhere except the
review UI, so the `is_private` shoulder-surfing lock does not apply to it.
Split it carefully: a private memory that comes out of a telling carries its
own `is_private` flag like any other.

## Queries this unlocks

| Question | Query shape |
|---|---|
| Memories from that telling | `telling_segments WHERE telling_id = ? AND memory_id IS NOT NULL` |
| Tellings that produced no memories | `tellings WHERE status = 'committed' AND no accepted segments` |
| Re-split after editing | transcript is retained; re-run segmentation |
| Undo a bad split | delete every `memory_id` recorded against a telling |

## Explicitly deferred

- **Speaker diarisation** ("who said what") — out of scope; a telling is
  first-person.
- **Very long tellings** — an hour-long recording will exceed one segmentation
  call's context. Chunking with overlap is the answer, but is deferred until
  a real transcript proves the need.
- **Storing audio** for re-transcription after a Whisper upgrade.
- **Tellings as a browsable entity** (a page listing past tellings) — the
  review UI is the only surface for now.
- **Editing the transcript after commit.**

## Decisions taken

- The input concept is called a **Telling**, never a Story.
- Drafts live in **`telling_segments`**, never in `memories`.
- The split is **reviewed before commit**; nothing enters `memories` implicitly.
- **The transcript is kept**; audio is not.
- **Relative dates resolve against a cursor** threaded through the narrative,
  not against today.
- **Precision coarsens, never sharpens**, when shifting a fuzzy date.
- Commit **reuses the normal entity and review-flag write path**.
