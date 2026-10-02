"""Which provider and model each agent role uses, and where that is decided.

Provider choice is per user: one person can point capture at a local model while
another uses a hosted one, each with their own key. A role a user has not set
falls back to the environment, so an untouched account keeps working exactly as
before settings existed.

Embeddings are different and are not a user choice: the vectors already stored
were produced by one model, and a different one yields vectors of another shape
that compare meaninglessly. The embedding *key* is settable; the model is not,
until re-embedding exists.
"""

import os
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# The agent roles a user can configure. Embeddings are deliberately absent:
# every stored vector was made by one model, so pointing them elsewhere would
# silently break search rather than improve it. They stay on the environment.
ROLES = (
    "capture",
    "refinement",
    "enrichment",
    "search",
    "telling",
    "story",
)
EMBEDDING_ROLE = "embedding"

DEFAULT_OLLAMA_API_BASE = "https://ollama.com/v1"
DEFAULT_OLLAMA_MODEL = "gemma4:31b"
DEFAULT_OLLAMA_EMBEDDING_MODEL = "nomic-embed-text"


@dataclass(frozen=True)
class LLMConfig:
    """The effective provider settings for one role.

    ``api_key`` is plaintext and exists only in memory; it is never returned by
    the API or written to a log.
    """

    role: str
    provider: str
    model: str
    api_base: Optional[str]
    api_key: Optional[str]

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


def env_default(role: str) -> LLMConfig:
    """The provider settings a role gets when the user has chosen nothing."""
    model = (
        os.getenv("OLLAMA_EMBEDDING_MODEL", DEFAULT_OLLAMA_EMBEDDING_MODEL)
        if role == EMBEDDING_ROLE
        else os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    )
    return LLMConfig(
        role=role,
        provider="ollama",
        model=model,
        api_base=os.getenv("OLLAMA_API_BASE", DEFAULT_OLLAMA_API_BASE),
        api_key=os.getenv("OLLAMA_API_KEY"),
    )


async def _load_row(
    db: AsyncSession, user_id: str, role: str
) -> Optional["object"]:
    from app.db import LLMSetting

    result = await db.execute(
        select(LLMSetting)
        .where(LLMSetting.user_id == user_id)
        .where(LLMSetting.role == role)
    )
    return result.scalars().first()


async def resolve(db: AsyncSession, user_id: str, role: str) -> LLMConfig:
    """The provider settings to use for a role, for one user.

    A stored row is merged over the environment default, so a user who set only
    a key still inherits the default model, and one who set only a model still
    inherits the default key.
    """
    base = env_default(role)
    row = await _load_row(db, user_id, role)
    if row is None:
        return base

    provider = row.provider or base.provider

    own_key = None
    if row.api_key_encrypted:
        from app.crypto import decrypt

        try:
            own_key = decrypt(row.api_key_encrypted)
        except Exception:
            # A key that cannot be read is treated as absent rather than fatal:
            # the caller degrades to its deterministic fallback.
            own_key = None

    # The env key and base both belong to the env provider. Carrying an Ollama
    # key or endpoint into a user's OpenAI config would send the request to the
    # wrong host and fail confusingly, so neither is inherited once the provider
    # changes; the adapter supplies the new provider's default instead.
    same_provider = provider == base.provider
    if own_key:
        api_key = own_key
    elif same_provider:
        api_key = base.api_key
    else:
        api_key = None

    return LLMConfig(
        role=role,
        provider=provider,
        model=row.model or base.model,
        api_base=row.api_base or (base.api_base if same_provider else None),
        api_key=api_key,
    )
