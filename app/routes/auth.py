"""Authentication routes (register, login, token refresh)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import uuid4
from pydantic import BaseModel

from app.db import User, get_db
from app.models.schemas import UserCreate, UserLogin, UserResponse, TokenResponse
from app.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse)
async def register(user_create: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user."""
    # Check if username already exists
    result = await db.execute(select(User).where(User.username == user_create.username))
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == user_create.email))
    existing_email = result.scalars().first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    # Create new user
    user = User(
        id=str(uuid4()),  # Convert to string for cross-DB compatibility
        username=user_create.username,
        email=user_create.email,
        password_hash=hash_password(user_create.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        created_at=user.created_at,
    )


@router.post("/login", response_model=TokenResponse)
async def login(user_login: UserLogin, db: AsyncSession = Depends(get_db)):
    """Login and get JWT token."""
    # Find user by username
    result = await db.execute(select(User).where(User.username == user_login.username))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Verify password
    if not verify_password(user_login.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Create access token
    access_token = create_access_token(
        user_id=str(user.id),
        username=user.username,
    )

    return TokenResponse(access_token=access_token)


class TokenRefreshRequest(BaseModel):
    """Token refresh request."""

    token: str


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: TokenRefreshRequest, db: AsyncSession = Depends(get_db)):
    """Refresh an expired token (returns new token if user exists)."""
    # Decode without enforcing expiration so a recently expired token can be
    # exchanged for a fresh one. The signature is still verified, and the user
    # must still exist.
    token_data = decode_access_token(req.token, verify_exp=False)

    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )

    # Verify user still exists
    result = await db.execute(select(User).where(User.id == token_data.user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    # Create new access token
    access_token = create_access_token(
        user_id=str(user.id),
        username=user.username,
    )

    return TokenResponse(access_token=access_token)
