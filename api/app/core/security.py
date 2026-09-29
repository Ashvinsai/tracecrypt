"""Password hashing. Argon2id via argon2-cffi; no home-grown cryptography (D008)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

#: Constant-time-ish decoy so a login against an unknown account costs the same
#: as one against a known account (B06).
DUMMY_HASH = _hasher.hash("password-that-is-never-valid")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Verify, always doing the work even when the account does not exist."""
    candidate = password_hash or DUMMY_HASH
    try:
        _hasher.verify(candidate, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
