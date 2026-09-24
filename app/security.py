"""Security utilities for JWT and password hashing."""

from datetime import datetime, timedelta
from typing import Optional
import os
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

# Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Inactivity timeout. The client enforces this by tracking user activity and
# signing out after a quiet period; the value is served to the client so a
# single .env setting drives the whole app.
DEFAULT_SESSION_IDLE_MINUTES = 15
DEFAULT_SESSION_IDLE_WARNING_SECONDS = 60


def get_session_idle_minutes() -> int:
    """Idle timeout in minutes, from SESSION_IDLE_MINUTES."""
    try:
        value = int(os.getenv("SESSION_IDLE_MINUTES", DEFAULT_SESSION_IDLE_MINUTES))
    except (TypeError, ValueError):
        return DEFAULT_SESSION_IDLE_MINUTES
    return max(1, value)


def get_session_idle_warning_seconds() -> int:
    """How long before logout to warn the user, from SESSION_IDLE_WARNING_SECONDS."""
    try:
        value = int(
            os.getenv(
                "SESSION_IDLE_WARNING_SECONDS", DEFAULT_SESSION_IDLE_WARNING_SECONDS
            )
        )
    except (TypeError, ValueError):
        return DEFAULT_SESSION_IDLE_WARNING_SECONDS
    # Never warn for longer than the timeout itself.
    return max(0, min(value, get_session_idle_minutes() * 60))

# Password hashing context
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


class TokenData(BaseModel):
    """JWT token payload data."""

    user_id: str
    username: str
    exp: Optional[datetime] = None


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    user_id: str, username: str, expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token."""
    to_encode = {
        "user_id": user_id,
        "username": username,
    }

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str, verify_exp: bool = True) -> Optional[TokenData]:
    """Decode and validate a JWT access token.

    Args:
        token: The encoded JWT.
        verify_exp: When False, an expired token still decodes successfully.
            Used by the refresh endpoint so a recently expired token can be
            exchanged for a new one.
    """
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_exp": verify_exp},
        )
        user_id: str = payload.get("user_id")
        username: str = payload.get("username")

        if user_id is None or username is None:
            return None

        return TokenData(user_id=user_id, username=username)
    except JWTError:
        return None
