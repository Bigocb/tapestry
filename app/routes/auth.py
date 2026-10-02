"""Authentication routes (register, login, token refresh)."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.db import PasswordResetToken, User, as_utc, get_db
from app.models.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)
from app.reset import (
    create_token,
    deliver,
    expiry_from_now,
    hash_token,
    reset_link,
    reset_requests_per_hour,
)
from app.dependencies import get_current_user
from app.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    get_session_idle_minutes,
    get_session_idle_warning_seconds,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# The same answer whether or not the account exists. Anything else would let
# anyone check who has an account here.
RESET_REQUESTED = (
    "If that account exists, a reset link has been created."
)


async def _find_user_by_identifier(db: AsyncSession, identifier: str):
    """Look an account up by username or email, case-insensitively."""
    needle = identifier.strip().lower()
    result = await db.execute(
        select(User).where(
            or_(
                func.lower(User.username) == needle,
                func.lower(User.email) == needle,
            )
        )
    )
    return result.scalar_one_or_none()


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start a password reset.

    Always answers identically, and never with the token. The link goes to the
    operator — by email when SMTP is configured, otherwise to the log.
    """
    user = await _find_user_by_identifier(db, payload.identifier)

    if user is not None:
        window_start = datetime.now(timezone.utc) - timedelta(hours=1)
        recent = await db.scalar(
            select(func.count())
            .select_from(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.created_at >= window_start.replace(tzinfo=None),
            )
        )

        # Rate limited per account: quietly skip rather than say so, since
        # saying so would reveal that the account exists.
        if (recent or 0) < reset_requests_per_hour():
            raw, hashed = create_token()
            db.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=hashed,
                    expires_at=expiry_from_now(),
                )
            )
            await db.commit()
            deliver(user.email, reset_link(raw))

    return {"detail": RESET_REQUESTED}


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Spend a reset link, and close every other outstanding one.

    An attacker who requested their own link earlier must not still have a way
    in after the real owner has reset their password.
    """
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_token(payload.token)
        )
    )
    token = result.scalar_one_or_none()

    if token is None or token.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That reset link is not valid.",
        )

    if as_utc(token.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That reset link has expired.",
        )

    user = await db.get(User, token.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That reset link is not valid.",
        )

    user.password_hash = hash_password(payload.new_password)

    now = datetime.now(timezone.utc)
    outstanding = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id
        )
    )
    for other in outstanding.scalars():
        other.used_at = now

    await db.commit()
    return {"detail": "Your password has been changed."}


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Change the signed-in user's password, given the current one.

    The current password is required even though a reset link exists: that link
    is for a forgotten password, and this is what stops a borrowed session from
    locking the owner out.
    """
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That is not your current password.",
        )

    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That is already your password.",
        )

    current_user.password_hash = hash_password(payload.new_password)

    # Any outstanding reset link was for the old password, so it no longer
    # applies. Closing them keeps a link requested before the change from
    # working after it.
    outstanding = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == current_user.id,
            PasswordResetToken.used_at.is_(None),
        )
    )
    now = datetime.now(timezone.utc)
    for token in outstanding.scalars():
        token.used_at = now

    await db.commit()
    return {"detail": "Your password has been changed."}


@router.get("/session-config")
async def session_config() -> dict:
    """Expose the session inactivity policy to the client.

    Unauthenticated on purpose: the login page needs the timeout value before
    a token exists. It contains no secrets.
    """
    idle_minutes = get_session_idle_minutes()
    return {
        "idle_timeout_seconds": idle_minutes * 60,
        "warning_seconds": get_session_idle_warning_seconds(),
    }


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

    # Create new user. The id default is a UUID object, which the GUID column
    # type adapts per-dialect; assigning a str here would make this row's id
    # a different Python type than a loaded one.
    user = User(
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
