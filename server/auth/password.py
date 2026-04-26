"""
server/auth/password.py — Password hashing and verification using bcrypt.

Uses bcrypt directly (bypasses passlib which has compatibility issues with bcrypt 4.x+).
"""

import bcrypt

_ROUNDS = 12


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plaintext password."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=_ROUNDS)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the stored bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
