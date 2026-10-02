"""Per-user settings: which provider and model each agent role uses.

Provider choice is per user, so one person can point capture at a local model
while another uses a hosted one. An untouched account keeps the environment
defaults exactly as before. API keys are accepted here, stored encrypted, and
never returned.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import encrypt
from app.db import LLMSetting, User, get_db
from app.dependencies import get_current_user
from app.llm_config import EMBEDDING_ROLE, ROLES, env_default
from app.models.schemas import LLMProviderSetting, LLMProviderSettingUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


def _as_response(role: str, row: LLMSetting | None) -> LLMProviderSetting:
    """The safe view of a role's setting: everything but the key itself."""
    default = env_default(role)
    provider = row.provider if row and row.provider else default.provider
    # The env key belongs to the env provider, so it only counts when the role
    # is still pointed there. Otherwise the honest answer is the user's own key.
    env_key_applies = provider == default.provider and bool(default.api_key)
    return LLMProviderSetting(
        role=role,
        provider=provider,
        model=(row.model if row and row.model else default.model),
        api_base=(row.api_base if row and row.api_base else default.api_base),
        has_api_key=bool(row and row.api_key_encrypted) or env_key_applies,
        locked_model=role == EMBEDDING_ROLE,
    )


async def _rows(db: AsyncSession, user_id: str) -> dict[str, LLMSetting]:
    result = await db.execute(
        select(LLMSetting).where(LLMSetting.user_id == user_id)
    )
    return {row.role: row for row in result.scalars().all()}


@router.get(
    "/llm",
    response_model=list[LLMProviderSetting],
    summary="List provider settings",
    description=(
        "One entry per agent role, reflecting the user's choice or the "
        "environment default. Never includes an API key."
    ),
)
async def list_llm_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LLMProviderSetting]:
    rows = await _rows(db, str(current_user.id))
    return [_as_response(role, rows.get(role)) for role in ROLES]


@router.put(
    "/llm/{role}",
    response_model=LLMProviderSetting,
    summary="Set a role's provider and model",
    description=(
        "Point an agent role at a provider and model. An omitted field is left "
        "alone; an empty api_key clears the stored one. The embedding model "
        "cannot be changed."
    ),
)
async def set_llm_setting(
    role: str,
    payload: LLMProviderSettingUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMProviderSetting:
    if role not in ROLES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown role '{role}'.",
        )

    if role == EMBEDDING_ROLE and payload.model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "The embedding model cannot be changed: every stored vector was "
                "made by one model, and another would not compare against them."
            ),
        )

    result = await db.execute(
        select(LLMSetting)
        .where(LLMSetting.user_id == str(current_user.id))
        .where(LLMSetting.role == role)
    )
    row = result.scalars().first()
    if row is None:
        row = LLMSetting(user_id=str(current_user.id), role=role)
        db.add(row)

    if payload.provider is not None:
        row.provider = payload.provider
    if payload.model is not None:
        row.model = payload.model
    if payload.api_base is not None:
        row.api_base = payload.api_base or None

    # Distinguish "omitted" from "cleared", the same as everywhere else: a key
    # is only replaced or removed when the field is present.
    if "api_key" in payload.model_fields_set:
        row.api_key_encrypted = encrypt(payload.api_key) if payload.api_key else None

    await db.commit()
    await db.refresh(row)
    return _as_response(role, row)
