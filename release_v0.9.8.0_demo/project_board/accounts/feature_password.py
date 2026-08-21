"""Password hashing and verification.

Uses stdlib hashlib.pbkdf2_hmac — no third-party crypto.
Each password gets a fresh random salt; the salt is stored alongside the
derived hash so verification can reproduce the same digest.

Stored format: ``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Final

# Iteration count — 200_000 follows current OWASP guidance for pbkdf2-sha256.
# Stored in the hash payload so we can raise it later without breaking old rows.
_ITERATIONS: Final[int] = 200_000
_SALT_BYTES: Final[int] = 16
_HASH_BYTES: Final[int] = 32
_ALGO_NAME: Final[str] = "pbkdf2_sha256"
_SEPARATOR: Final[str] = "$"


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=_HASH_BYTES,
    )


def hash_password(password: str) -> str:
    """Hash a plaintext password into a self-describing string.

    Returned value embeds algorithm name, iteration count, salt, and digest
    so future verifiers can adapt without external metadata.
    """
    if not isinstance(password, str) or password == "":
        raise ValueError("password must be a non-empty string")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _derive(password, salt, _ITERATIONS)
    return _SEPARATOR.join(
        [
            _ALGO_NAME,
            str(_ITERATIONS),
            salt.hex(),
            digest.hex(),
        ]
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a stored hash string.

    Returns False for any malformed stored value rather than raising — callers
    should treat malformed storage as a verification failure, not a crash.
    """
    if not isinstance(password, str) or not isinstance(stored, str):
        return False
    parts = stored.split(_SEPARATOR)
    if len(parts) != 4:
        return False
    algo, iter_str, salt_hex, hash_hex = parts
    if algo != _ALGO_NAME:
        return False
    try:
        iterations = int(iter_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    candidate = _derive(password, salt, iterations)
    return hmac.compare_digest(candidate, expected)
