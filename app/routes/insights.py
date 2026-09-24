"""Insights routes (Issue 18).

Aggregate stats, trends, word cloud, and achievements derived from a user's
memories and stories. All endpoints are scoped to the authenticated user.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
from collections import Counter
import re

from app.db import get_db, Memory, Story, User
from app.dependencies import get_current_user
from app.models.schemas import (
    Achievement,
    MemoryStats,
    MemoryTrends,
    TrendData,
    WordCloudData,
)
from app.privacy import get_unlocked_memory_ids, is_locked

router = APIRouter()


# Common English stopwords excluded from the word cloud.
_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an",
    "and", "any", "are", "aren", "as", "at", "be", "because", "been", "before",
    "being", "below", "between", "both", "but", "by", "can", "cannot", "could",
    "couldn", "did", "didn", "do", "does", "doesn", "doing", "don", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn", "has",
    "hasn", "have", "haven", "having", "he", "her", "here", "hers", "herself",
    "him", "himself", "his", "how", "i", "if", "in", "into", "is", "isn", "it",
    "its", "itself", "just", "me", "more", "most", "my", "myself", "no", "nor",
    "not", "now", "of", "off", "on", "once", "only", "or", "other", "our",
    "ours", "ourselves", "out", "over", "own", "same", "she", "should",
    "shouldn", "so", "some", "such", "than", "that", "the", "their", "theirs",
    "them", "themselves", "then", "there", "these", "they", "this", "those",
    "through", "to", "too", "under", "until", "up", "very", "was", "wasn",
    "we", "were", "weren", "what", "when", "where", "which", "while", "who",
    "whom", "why", "will", "with", "won", "would", "wouldn", "you", "your",
    "yours", "yourself", "yourselves",
}

# Rough positivity mapping for mood trends.
_MOOD_SCORES = {
    "happy": 1.0,
    "joyful": 1.0,
    "excited": 0.9,
    "grateful": 0.9,
    "content": 0.8,
    "proud": 0.8,
    "calm": 0.7,
    "neutral": 0.5,
    "tired": 0.4,
    "anxious": 0.3,
    "stressed": 0.3,
    "sad": 0.2,
    "angry": 0.1,
}


def _week_start(moment: datetime) -> datetime:
    """Return the UTC Monday 00:00 of the week containing ``moment``."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=midnight.weekday())


def _memory_date(memory: Memory) -> datetime:
    """Return the date used for time-based aggregation."""
    return memory.event_date or memory.created_at


async def _load_user_memories(
    db: AsyncSession, user_id, unlocked_ids: set[str] | None = None
) -> list[Memory]:
    """Fetch the user's memories, excluding any still locked.

    Locked memories are omitted so aggregate output (moods, tags, word cloud)
    cannot leak their contents.
    """
    result = await db.execute(select(Memory).where(Memory.user_id == user_id))
    unlocked_ids = unlocked_ids or set()
    return [m for m in result.scalars().all() if not is_locked(m, unlocked_ids)]


@router.get(
    "/insights/stats",
    response_model=MemoryStats,
    summary="Aggregate memory statistics",
    description="Total memories plus counts by mood and tag and average importance.",
)
async def get_insights_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> MemoryStats:
    """Return aggregate statistics for the current user's memories."""
    memories = await _load_user_memories(db, current_user.id, unlocked_ids)

    total = len(memories)
    mood_counts: Counter = Counter()
    tag_counts: Counter = Counter()
    importance_total = 0

    for memory in memories:
        mood_counts[memory.mood or "unknown"] += 1
        for tag in memory.tags or []:
            tag_counts[tag] += 1
        importance_total += memory.importance_level or 0

    average_importance = round(importance_total / total, 4) if total else 0.0

    return MemoryStats(
        total_memories=total,
        memories_by_mood=dict(mood_counts),
        memories_by_tag=dict(tag_counts),
        average_importance=average_importance,
    )


@router.get(
    "/insights/trends",
    response_model=MemoryTrends,
    summary="Memory trends over time",
    description="Memories per week and average mood per week.",
)
async def get_insights_trends(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> MemoryTrends:
    """Return weekly memory counts and mood trends."""
    memories = await _load_user_memories(db, current_user.id, unlocked_ids)

    per_week: Counter = Counter()
    mood_sums: dict[datetime, float] = {}
    mood_counts: dict[datetime, int] = {}

    for memory in memories:
        week = _week_start(_memory_date(memory))
        per_week[week] += 1

        if memory.mood:
            score = _MOOD_SCORES.get(memory.mood.lower())
            if score is not None:
                mood_sums[week] = mood_sums.get(week, 0.0) + score
                mood_counts[week] = mood_counts.get(week, 0) + 1

    memories_per_week = [
        TrendData(timestamp=week, value=float(count))
        for week, count in sorted(per_week.items())
    ]

    mood_trend = [
        TrendData(timestamp=week, value=round(mood_sums[week] / mood_counts[week], 4))
        for week in sorted(mood_sums)
        if mood_counts[week]
    ]

    return MemoryTrends(memories_per_week=memories_per_week, mood_trend=mood_trend)


@router.get(
    "/insights/word-cloud",
    response_model=list[WordCloudData],
    summary="Word frequency cloud",
    description="Most frequent words across memory titles and summaries.",
)
async def get_insights_word_cloud(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> list[WordCloudData]:
    """Return the most frequent non-stopword terms in the user's memories."""
    memories = await _load_user_memories(db, current_user.id, unlocked_ids)

    counts: Counter = Counter()
    for memory in memories:
        content = memory.structured_content if isinstance(memory.structured_content, dict) else {}
        text = " ".join(
            part
            for part in (
                content.get("title"),
                content.get("summary"),
                memory.raw_input,
            )
            if part
        )
        for word in re.findall(r"[a-zA-Z']+", text.lower()):
            if len(word) < 3 or word in _STOPWORDS:
                continue
            counts[word] += 1

    limit = max(1, min(200, limit))
    return [
        WordCloudData(word=word, frequency=frequency)
        for word, frequency in counts.most_common(limit)
    ]


@router.get(
    "/insights/achievements",
    response_model=list[Achievement],
    summary="Earned achievements",
    description="Badges and milestones based on the user's memory and story activity.",
)
async def get_insights_achievements(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> list[Achievement]:
    """Return achievement progress for the current user."""
    memories = await _load_user_memories(db, current_user.id, unlocked_ids)
    story_result = await db.execute(
        select(Story).where(Story.user_id == current_user.id)
    )
    stories = list(story_result.scalars().all())

    memory_count = len(memories)
    story_count = len(stories)

    def milestone(
        achievement_id: str,
        name: str,
        description: str,
        value: int,
        threshold: int,
    ) -> Achievement:
        earned = value >= threshold
        progress = 1.0 if earned else round(value / threshold, 4)
        return Achievement(
            id=achievement_id,
            name=name,
            description=description,
            earned=earned,
            progress=progress,
        )

    return [
        milestone(
            "first_memory",
            "First Memory",
            "Capture your first memory",
            memory_count,
            1,
        ),
        milestone(
            "ten_memories",
            "Getting Started",
            "Capture 10 memories",
            memory_count,
            10,
        ),
        milestone(
            "fifty_memories",
            "Memory Keeper",
            "Capture 50 memories",
            memory_count,
            50,
        ),
        milestone(
            "hundred_memories",
            "Centurion",
            "Capture 100 memories",
            memory_count,
            100,
        ),
        milestone(
            "first_story",
            "Storyteller",
            "Generate your first story",
            story_count,
            1,
        ),
        milestone(
            "ten_stories",
            "Author",
            "Generate 10 stories",
            story_count,
            10,
        ),
    ]
