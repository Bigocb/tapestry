"""Tests for Pydantic data models.

RED: Verify that all Pydantic models validate data correctly.
- User models (create, login, response)
- Memory models (capture, response, update)
- Entity models
- Search models
- Story models
- Insights models
"""

import pytest
from datetime import datetime
from uuid import uuid4
from pydantic import ValidationError

from app.models.schemas import (
    UserCreate,
    UserLogin,
    UserResponse,
    EntityData,
    MemoryCapture,
    MemoryResponse,
    MemoryUpdate,
    SearchQuery,
    SearchFilters,
    StoryGenerate,
    StoryResponse,
    MemoryStats,
)


class TestUserModels:
    """Test user-related Pydantic models."""

    def test_user_create_valid(self):
        """Valid user creation."""
        user = UserCreate(
            username="testuser", email="test@example.com", password="securepassword123"
        )
        assert user.username == "testuser"
        assert user.email == "test@example.com"

    def test_user_create_invalid_username_too_short(self):
        """Username too short (< 3 chars)."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                username="ab", email="test@example.com", password="securepassword123"
            )
        assert "at least 3 characters" in str(exc_info.value)

    def test_user_create_invalid_username_special_chars(self):
        """Username with invalid special characters."""
        with pytest.raises(ValidationError):
            UserCreate(
                username="test@user!",
                email="test@example.com",
                password="securepassword123",
            )

    def test_user_create_valid_username_with_underscore(self):
        """Username with underscore and hyphen."""
        user = UserCreate(
            username="test_user-123",
            email="test@example.com",
            password="securepassword123",
        )
        assert user.username == "test_user-123"

    def test_user_create_invalid_email(self):
        """Invalid email format."""
        with pytest.raises(ValidationError):
            UserCreate(
                username="testuser", email="not-an-email", password="securepassword123"
            )

    def test_user_create_password_too_short(self):
        """Password too short (< 8 chars)."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(username="testuser", email="test@example.com", password="short")
        assert "at least 8 characters" in str(exc_info.value)

    def test_user_login_valid(self):
        """Valid user login."""
        login = UserLogin(username="testuser", password="password123")
        assert login.username == "testuser"

    def test_user_response_valid(self):
        """Valid user response."""
        user_id = uuid4()
        user = UserResponse(
            id=user_id,
            username="testuser",
            email="test@example.com",
            created_at=datetime.now(),
        )
        assert user.id == user_id
        assert user.username == "testuser"


class TestEntityModels:
    """Test entity-related Pydantic models."""

    def test_entity_data_valid_person(self):
        """Valid person entity."""
        entity = EntityData(
            type="person", value="Sarah", metadata={"role": "colleague"}
        )
        assert entity.type == "person"
        assert entity.value == "Sarah"

    def test_entity_data_valid_place(self):
        """Valid place entity."""
        entity = EntityData(type="place", value="New York City")
        assert entity.type == "place"

    def test_entity_data_invalid_type(self):
        """Invalid entity type."""
        with pytest.raises(ValidationError):
            EntityData(type="invalid_type", value="something")

    def test_entity_data_all_valid_types(self):
        """All valid entity types work."""
        valid_types = ["person", "place", "date", "event", "concept"]
        for entity_type in valid_types:
            entity = EntityData(type=entity_type, value="test value")
            assert entity.type == entity_type


class TestMemoryModels:
    """Test memory-related Pydantic models."""

    def test_memory_capture_text(self):
        """Valid text memory capture."""
        memory = MemoryCapture(
            raw_input="I had coffee with Sarah today", input_type="text"
        )
        assert memory.input_type == "text"

    def test_memory_capture_voice(self):
        """Valid voice memory capture."""
        memory = MemoryCapture(
            raw_input="transcribed voice text...", input_type="voice"
        )
        assert memory.input_type == "voice"

    def test_memory_capture_form(self):
        """Valid form memory capture."""
        memory = MemoryCapture(raw_input="form data", input_type="form")
        assert memory.input_type == "form"

    def test_memory_capture_invalid_input_type(self):
        """Invalid input type."""
        with pytest.raises(ValidationError):
            MemoryCapture(raw_input="some input", input_type="invalid")

    def test_memory_response_valid(self):
        """Valid complete memory response."""
        memory_id = uuid4()
        user_id = uuid4()
        memory = MemoryResponse(
            id=memory_id,
            user_id=user_id,
            raw_input="Coffee with Sarah",
            input_type="text",
            processing_state="raw",
            tags=["work"],
            importance_level=7,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert memory.id == memory_id
        assert memory.importance_level == 7

    def test_memory_response_importance_level_invalid(self):
        """Importance level out of range."""
        with pytest.raises(ValidationError) as exc_info:
            MemoryResponse(
                id=uuid4(),
                user_id=uuid4(),
                raw_input="test",
                input_type="text",
                processing_state="raw",
                importance_level=11,  # Should be 1-10
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        assert "less than or equal to 10" in str(exc_info.value)

    def test_memory_update_partial(self):
        """Partial memory update (all fields optional)."""
        update = MemoryUpdate(tags=["work", "social"], importance_level=8)
        assert update.tags == ["work", "social"]
        assert update.raw_input is None

    def test_memory_update_empty(self):
        """Empty memory update is valid."""
        update = MemoryUpdate()
        assert update.tags is None
        assert update.raw_input is None


class TestSearchModels:
    """Test search-related Pydantic models."""

    def test_search_query_text_only(self):
        """Search by text only."""
        query = SearchQuery(text="coffee meeting")
        assert query.text == "coffee meeting"
        assert query.semantic is None

    def test_search_query_semantic_only(self):
        """Search by semantic meaning."""
        query = SearchQuery(semantic="casual professional conversations")
        assert query.semantic == "casual professional conversations"

    def test_search_query_with_filters(self):
        """Search with filters."""
        filters = SearchFilters(mood="happy", importance_min=5, tags=["work"])
        query = SearchQuery(text="meeting", filters=filters, limit=50)
        assert query.filters.mood == "happy"
        assert query.limit == 50

    def test_search_query_limit_constraints(self):
        """Limit must be between 1 and 100."""
        with pytest.raises(ValidationError):
            SearchQuery(text="test", limit=0)

        with pytest.raises(ValidationError):
            SearchQuery(text="test", limit=101)

    def test_search_filters_date_range(self):
        """Search by date range."""
        start = datetime(2024, 7, 1)
        end = datetime(2024, 7, 31)
        filters = SearchFilters(date_range_start=start, date_range_end=end)
        assert filters.date_range_start == start


class TestStoryModels:
    """Test story-related Pydantic models."""

    def test_story_generate_chronological(self):
        """Generate chronological story."""
        memory_ids = [uuid4(), uuid4(), uuid4()]
        story = StoryGenerate(memory_ids=memory_ids, story_type="chronological")
        assert len(story.memory_ids) == 3
        assert story.story_type == "chronological"

    def test_story_generate_thematic(self):
        """Generate thematic story."""
        story = StoryGenerate(memory_ids=[uuid4(), uuid4()], story_type="thematic")
        assert story.story_type == "thematic"

    def test_story_generate_curated(self):
        """Generate curated highlight reel."""
        story = StoryGenerate(
            memory_ids=[uuid4(), uuid4(), uuid4()], story_type="curated"
        )
        assert story.story_type == "curated"

    def test_story_generate_digest(self):
        """Generate weekly/monthly digest."""
        story = StoryGenerate(memory_ids=[uuid4()], story_type="digest")
        assert story.story_type == "digest"

    def test_story_generate_all_valid_types(self):
        """All valid story types work."""
        valid_types = ["chronological", "thematic", "curated", "digest"]
        for story_type in valid_types:
            story = StoryGenerate(memory_ids=[uuid4()], story_type=story_type)
            assert story.story_type == story_type

    def test_story_generate_invalid_type(self):
        """Invalid story type."""
        with pytest.raises(ValidationError):
            StoryGenerate(memory_ids=[uuid4()], story_type="invalid_type")

    def test_story_generate_empty_memory_ids(self):
        """Empty memory IDs list is invalid."""
        with pytest.raises(ValidationError):
            StoryGenerate(memory_ids=[], story_type="chronological")

    def test_story_generate_with_custom_prompt(self):
        """Story generation with custom prompt."""
        story = StoryGenerate(
            memory_ids=[uuid4(), uuid4()],
            story_type="chronological",
            custom_prompt="Make it funny and uplifting",
        )
        assert story.custom_prompt == "Make it funny and uplifting"

    def test_story_response_valid(self):
        """Valid story response."""
        story_id = uuid4()
        user_id = uuid4()
        memory_ids = [uuid4(), uuid4()]
        story = StoryResponse(
            id=story_id,
            user_id=user_id,
            title="My Week in Memories",
            narrative="# My Week\n\nOn Monday, I...",
            memory_ids=memory_ids,
            story_type="digest",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert story.id == story_id
        assert story.story_type == "digest"


class TestInsightsModels:
    """Test insights and statistics models."""

    def test_memory_stats_valid(self):
        """Valid memory statistics."""
        stats = MemoryStats(
            total_memories=42,
            memories_by_mood={"happy": 15, "neutral": 20, "sad": 7},
            memories_by_tag={"work": 25, "personal": 17},
            average_importance=6.5,
        )
        assert stats.total_memories == 42
        assert stats.memories_by_mood["happy"] == 15

    def test_memory_stats_empty(self):
        """Memory stats with no data."""
        stats = MemoryStats(total_memories=0, average_importance=0.0)
        assert stats.total_memories == 0
