# Tapestry Enrichment Ideas

## Overview

During the **Enrichment Agent** phase (Issue 8), we enrich memories with additional context beyond what the user provided. This document brainstorms what data sources and enrichments could be valuable.

## Current Enrichment (Approved)

From the PRD, the Enrichment Agent currently:
1. **Generate embeddings** via Ollama for semantic search
2. **Retrieve related memories** (RAG from pgvector)
3. **Suggest tags** based on content and similar memories
4. **Set importance level** intelligently
5. **Extract thematic connections** between memories

---

## Additional Enrichment Ideas to Explore

### 1. **Location-Based Enrichment** 📍

**What to capture:**
- Where was the memory created? (GPS, manual entry, IP geolocation)
- What's special about this location?

**Data sources:**
- **Reverse geocoding** (coordinates → address)
  - Service: Google Maps API, Nominatim (OSM), or local
  - Returns: Street address, city, country, zip code
  
- **Location metadata** (what's nearby?)
  - Restaurants, landmarks, weather station
  - Public events or attractions
  
- **Weather at time of memory**
  - Temperature, precipitation, conditions
  - Sunrise/sunset times
  - Air quality

**Use cases:**
- "Show me memories from coffee shops in NYC"
- "What was I doing on that sunny day in July?"
- "Memories from my road trip to California"
- "Favorite locations for reflection"

**Implementation approach:**
- Optional: User grants location permission
- Store location_id, address, coordinates, weather_snapshot in memory
- Enrich async: fetch weather history from API

---

### 2. **Temporal Enrichment** 📅

**What to capture:**
- Time of day, day of week, season
- Time relative to other events (holidays, user milestones)

**Data sources:**
- **Calendar integration** (Google, Outlook, Apple)
  - What was scheduled that day?
  - Which events actually happened?
  
- **Holidays & observances**
  - National holidays, cultural observances
  - User-defined personal milestones
  
- **Moon phases, astrology** (optional/fun)
  - Phase of the moon
  - Astrological sign
  - Sunrise/sunset

**Use cases:**
- "What was I doing around my birthday?"
- "Memories from my work events"
- "Reflections on New Year's Eve"
- "Patterns across seasons"

**Implementation approach:**
- Extract day/time from memory creation timestamp
- Optional: User connects calendar API (OAuth)
- Look up holidays via simple API (holiday.calendar.is, calendarific.com)

---

### 3. **News & Events Enrichment** 📰

**What to capture:**
- What was happening in the world when this memory was created?
- Major events, stories, trends

**Data sources:**
- **News API** (newsapi.org, nytimes API, etc.)
  - Top news on the day of the memory
  - Trending topics
  
- **Social media trends** (optional)
  - Twitter/X trending topics
  - Hashtag trends
  
- **Local news** (if location known)
  - Local events, incidents, announcements
  - Community news

**Use cases:**
- "What was big news when I wrote this?"
- "See my memories contextualized with world events"
- "Timeline of my personal life vs. history"
- "My memories during COVID, the election, etc."

**Implementation approach:**
- Call news API with memory creation date
- Cache trending news (expensive to fetch per memory)
- Optional: user controls which news sources

---

### 4. **Music & Media Enrichment** 🎵

**What to capture:**
- What was playing when this memory was created?
- Music taste at that time

**Data sources:**
- **Spotify API** (if user connects)
  - What was user listening to that day?
  - Top tracks/artists that week/month
  
- **Music streaming stats**
  - All-time favorites
  - Discovery playlist
  
- **Movie/TV releases**
  - Popular movies/shows released that week
  - What was user watching?

**Use cases:**
- "This memory is connected to my Spotify Wrapped 2024"
- "I remember listening to this song when I wrote this"
- "See the soundtrack of my life"
- "Memories from my favorite movies/shows"

**Implementation approach:**
- Optional: User connects Spotify OAuth
- Fetch listening history for memory date range
- Store music_context: top_tracks, current_playing, etc.

---

### 5. **Health & Wellness Enrichment** 💪

**What to capture:**
- Physical/mental state at time of memory
- Health trends

**Data sources:**
- **Fitness tracker APIs** (Apple Health, Garmin, Fitbit, Strava)
  - Steps, exercise, sleep quality
  - Heart rate, mood tracking
  
- **Health data**
  - Steps walked that day
  - Calories burned
  - Sleep hours
  
- **Mood/wellness tracking**
  - User-provided mood (separate from memory mood)
  - Energy level, stress level

**Use cases:**
- "My memories from days I exercised"
- "Insights during high-stress periods"
- "Correlation: more exercise → happier memories?"
- "Sleep quality vs. memory quality?"

**Implementation approach:**
- Optional: User connects fitness tracker API
- Enrichment pulls health_snapshot for memory date
- Stores: steps, exercise_minutes, sleep_hours, etc.

---

### 6. **Social & Relationship Enrichment** 👥

**What to capture:**
- Who is mentioned in the memory?
- Relationship context

**Data sources:**
- **Extracted entities** (already in Enrichment Agent)
  - People mentioned
  - Relationships between people
  
- **Contact frequency**
  - How often do you mention this person?
  - When was last memory with them?
  
- **Relationship patterns**
  - Cluster memories by person
  - Connection strength graph

**Use cases:**
- "All memories mentioning Sarah"
- "My friendship with [person] over time"
- "Who do I think about most?"
- "Reconnect: haven't written about X in 6 months"

**Implementation approach:**
- Entity extraction (already done)
- Build person_id references
- Count mentions, time since last mention
- Optional: user defines relationships

---

### 7. **Sentiment & Emotion Enrichment** 😊

**What to capture:**
- Emotional tone of the memory
- Sentiment analysis

**Data sources:**
- **Sentiment analysis** (Ollama, HuggingFace, or simple)
  - Positive, negative, neutral score
  - Specific emotions (joy, sadness, anger, etc.)
  
- **Sentiment trends**
  - Overall mood trend over time
  - Mood by person, location, topic

**Use cases:**
- "My happiest memories"
- "Moments of growth (from sad to happy)"
- "Emotional timeline of my year"
- "What makes me feel [emotion]?"

**Implementation approach:**
- Sentiment analysis on raw_input + title
- Store sentiment_score, emotion_tags
- Track sentiment_trend over time

---

### 8. **Learning & Growth Enrichment** 🧠

**What to capture:**
- Lessons learned from this memory
- Personal growth indicators

**Data sources:**
- **AI-extracted lessons**
  - Agent extracts key learnings/insights
  - Patterns across memories
  
- **Skill development tracking**
  - Skills mentioned
  - Progress over time
  
- **Goal progress**
  - Goals mentioned
  - Milestones achieved

**Use cases:**
- "Lessons I've learned"
- "Skills I'm developing"
- "My personal goals and progress"
- "Growth arc over the year"

**Implementation approach:**
- Use Ollama to extract lessons/insights
- Store lessons_extracted: [list of strings]
- Match against skills/goals database
- Display growth graph

---

### 9. **Weather & Environment Enrichment** 🌤️

Already covered under Location, but worth emphasizing:

**Data sources:**
- **Weather history API**
  - OpenWeatherMap, NOAA, local weather service
  - Conditions, temperature, wind, humidity
  
- **Air quality**
  - AQI (Air Quality Index)
  - Pollution levels
  
- **Environmental events**
  - Storms, natural disasters
  - Severe weather alerts

**Use cases:**
- "Memories from rainy days"
- "How does weather affect my mood?"
- "Trip memories with weather context"

---

### 10. **Accessibility & Privacy-Respecting Enrichment** 🔒

**Principles:**
- **Opt-in only** - User chooses what to enrich
- **Data minimization** - Only store what's needed
- **Privacy first** - No tracking/surveillance
- **Local-first where possible** - Weather via zip code, not GPS
- **One-time permission** - Ask once, use consistently
- **Easy to disable** - User can turn off any enrichment

**Implementation approach:**
- Enrichment settings UI: toggle each data source
- Clear explanation of what data is collected
- Regular audits: show user what was enriched
- Easy deletion: remove enrichment data on request

---

## Recommendation for MVP

**Phase 1 (Current Issues):**
- ✓ RAG (retrieve related memories)
- ✓ Tags & importance
- ✓ Embeddings

**Phase 2 Recommended (Next PRD revision):**
1. **Location enrichment** (moderate complexity, high value)
   - Reverse geocoding + optional weather
   - ~2-3 days of work
   
2. **Temporal enrichment** (low complexity, medium value)
   - Day of week, holidays, seasons
   - ~1 day of work

3. **Sentiment enrichment** (low complexity, high value)
   - Sentiment analysis + emotion extraction
   - ~1-2 days of work

**Phase 3+ (Future phases):**
- News enrichment (complex API, medium value)
- Music enrichment (requires OAuth, high fun factor)
- Health enrichment (complex OAuth, specialized)
- Social enrichment (requires relationship modeling)
- Learning enrichment (complex AI reasoning)

---

## Questions for Discussion

1. **Privacy vs. functionality:** How much data should we ask for?
   - Location (GPS vs. manual entry)?
   - Calendar integration?
   - Fitness trackers?

2. **Cost:** Which enrichments have API costs?
   - News APIs (paid tiers)
   - Maps/geocoding (free tier exists)
   - Weather (free tier exists)
   - Sentiment analysis (free via Ollama)

3. **User control:** How granular should enrichment settings be?
   - Global toggle per enrichment type?
   - Per-memory toggle?
   - Selective retroactive enrichment?

4. **Data retention:** How long to keep enrichment data?
   - Weather snapshots (small, keep forever)
   - News snapshots (medium, keep 1 year?)
   - Third-party data (follow their terms)

---

## Implementation Order (Proposed)

Assuming 4-week development cycle:

**Week 1:** Location + Weather enrichment
**Week 2:** Temporal enrichment + Sentiment analysis
**Week 3:** News enrichment (low priority, can skip)
**Week 4:** Polish, testing, optimization

This would create a rich, multi-dimensional memory experience without overwhelming the user.

