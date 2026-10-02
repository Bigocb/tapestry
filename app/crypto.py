"""Encrypting secrets at rest, for the things a user pastes in.

Provider API keys arrive through the browser, so they have to be stored
somehow. They are encrypted with a key that lives only in the environment, not
in the database — a database dump on its own is then not enough to read them.

The key is derived from ``SECRET_ENCRYPTION_KEY`` with HKDF, so any length of
passphrase works and rotating it is a matter of re-saving the keys.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

_ENV_VAR = "SECRET_ENCRYPTION_KEY"


class EncryptionUnavailable(RuntimeError):
    """Raised when no encryption key is configured."""


class DecryptionFailed(RuntimeError):
    """Raised when a stored value cannot be read with the current key."""


def _cipher() -> Fernet:
    import os

    secret = os.getenv(_ENV_VAR)
    if not secret:
        raise EncryptionUnavailable(
            f"{_ENV_VAR} is not set; refusing to store or read secrets."
        )
    # HKDF-Expand: the salt and info are fixed because there is a single use.
    derived = hashlib.pbkdf2_hmac(
        "sha256", secret.encode(), b"tapestry-llm-keys", 100_000, dklen=32
    )
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt(plaintext: str) -> str:
    """Encrypt a secret for storage."""
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Read a stored secret back, or raise if it cannot be read."""
    try:
        return _cipher().decrypt(token.encode()).decode()
    except InvalidToken as error:
        raise DecryptionFailed(
            "A stored secret could not be read; the encryption key may have changed."
        ) from error
