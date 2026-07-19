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
2. Decodes the token (currently without strict expiration checking — see note below)
3. Verifies the user still exists in the database
4. Issues a new token with a fresh expiration

> **Note**: The current refresh implementation decodes the token without verifying expiration. This is documented as a simplification; production use would require a separate refresh token mechanism with proper expiration handling.

## Route Protection

Protected endpoints use the `get_current_user` dependency from [`app/dependencies.py`](../app/dependencies.py):

1. Extracts the Bearer token from the `Authorization` header via `HTTPBearer`
2. Decodes the JWT and extracts `user_id` and `username`
3. Loads the `User` from the database by `user_id`
4. Returns the `User` ORM object for use in the route handler

All memory-related endpoints (e.g., `POST /api/memories/capture`) require authentication via this dependency.

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

- The default secret key should never be used in production; set `JWT_SECRET_KEY` via environment variable
- CORS currently allows `localhost:3000` and `localhost:8000` — restrict in production
- Token refresh does not currently validate expiration strictly
- No rate limiting on registration or login endpoints yet