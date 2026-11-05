"""Password hashing and session token primitives."""

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()  # Argon2id with library-recommended parameters


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_session_token() -> str:
    """Opaque, high-entropy token handed to the client in an httpOnly cookie."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Only a keyed hash of the token is stored, so a DB leak can't be replayed."""
    key = get_settings().secret_key.encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


# A constant dummy hash used to equalize timing when a user does not exist.
DUMMY_PASSWORD_HASH = _hasher.hash("timing-equalizer-not-a-real-password")
