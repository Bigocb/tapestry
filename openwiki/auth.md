---
type: Reference
title: MEMIND Authentication
description: JWT authentication flow, password hashing, token refresh, and route protection in MEMIND.
tags: [memind, auth, jwt, security]
---

# Authentication

MEMIND uses JWT-based stateless authentication. All protected endpoints require a Bearer token in the `Authorization` header. Token claims are defined by Pydantic models in [Data Models](data-models.md) and the full application structure is described in [Architecture](architecture.md).

## Registration Flow

`POST /api/auth/register` — [`app/routes/auth.py`](../app/routes/auth.py)

1. Accepts `UserCreate` schema (username, email, password)
2. Validates username format (alphanumeric, underscores, hyphens) and password length (≥ 8 chars)
3. Checks for duplicate username and email
4. Hashes password with bcrypt via passlib
5. Creates a `User` row in the database
6. Returns `UserResponse` (id, username, email, created_at) — **no token returned on registration**

## Login Flow

`POST /api/auth/login` — [`app/routes/auth.py`](../app/routes/auth.py)

1. Accepts `UserLogin` schema (username, password)
2. Looks up user by username
3. Verifies password against bcrypt hash via `verify_password()`
4. Creates a JWT access token containing `user_id` and `username` claims
5. Returns `TokenResponse` with `access_token` and `token_type: "bearer"`

## Token Refresh

`POST /api/auth/refresh` — [`app/routes/auth.py`](../app/routes/auth.py)

1. Accepts `TokenRefreshRequest` containing the existing token
2. Decodes it with `verify_exp=False`, so a **recently expired** token can be
   exchanged for a fresh one (the signature is still verified)
3. Verifies the user still exists
4. Issues a new token with a fresh expiration

> **Note**: `decode_access_token(token, verify_exp=...)` exists for this reason.
> Everywhere else expiration is enforced. A production setup would add a
> separate refresh token with its own lifetime rather than reusing the access
> token.

## Session Inactivity Timeout

The client enforces an idle timeout, not the server:

- `GET /api/auth/session-config` (unauthenticated) returns
  `{idle_timeout_seconds, warning_seconds}` from `SESSION_IDLE_MINUTES` and
  `SESSION_IDLE_WARNING_SECONDS`
- The frontend tracks activity, warns with a live countdown, and signs out
  when the period elapses

It is unauthenticated on purpose: the login page needs the policy before a token
exists, and it contains no secrets. Because enforcement is client-side it is a
privacy convenience rather than a hard security boundary.

## Route Protection

Protected endpoints use the `get_current_user` dependency from [`app/dependencies.py`](../app/dependencies.py):

1. Extracts the Bearer token from the `Authorization` header via `HTTPBearer`
2. Decodes the JWT and extracts `user_id` and `username`
3. Loads the `User` from the database by `user_id`
4. Returns the `User` ORM object for use in the route handler

Every protected query additionally filters by `user_id`, so users cannot read
each other's data even by guessing ids.

## JWT Configuration

Defined in [`app/security.py`](../app/security.py):

| Setting | Value | Notes |
|---------|-------|-------|
| Algorithm | HS256 | HMAC-SHA256 |
| Expiration | 30 minutes | `ACCESS_TOKEN_EXPIRE_MINUTES` |
| Secret key | `JWT_SECRET_KEY` env var | Falls back to `dev-secret-key-change-in-production` |

## Password Security

- **Hashing**: bcrypt via `passlib.context.CryptContext` with `deprecated="auto"`
- **Verification**: `passlib.verify()` against the stored hash
- Minimum password length: 8 characters (enforced by Pydantic schema)

## Testing

Auth tests in [`tests/test_auth.py`](../tests/test_auth.py) cover:

- User registration (valid, duplicate username, duplicate email, short password)
- Login (valid, invalid password, non-existent user)
- Token creation and decoding
- Protected route access with valid and invalid tokens
- User isolation (user A cannot access user B's data)

All 20 auth tests pass against SQLite in-memory database.

## Security Considerations

- The default secret key must never be used in production; set `JWT_SECRET_KEY`
- CORS currently allows `localhost:3000` and `localhost:8000` — restrict in production
- The idle timeout is enforced client-side, so it is not tamper-proof
- No rate limiting on registration or login yet
- The privacy lock is a shoulder-surfing shield: any authenticated user of the
  account can unlock any memory