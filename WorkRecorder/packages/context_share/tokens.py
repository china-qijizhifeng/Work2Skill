"""Opaque share token helpers."""

from __future__ import annotations

import hashlib
import secrets


def new_share_token() -> str:
    """Return a URL-safe secret token used for future unauthenticated share gates.

    Returns:
        Random token suitable for hashing and storing as a verifier.
    """

    return secrets.token_urlsafe(24)


def token_hash(token: str) -> str:
    """Hash a share token before storing it in SQLite.

    Args:
        token: Opaque share token returned by the token generator.

    Returns:
        SHA-256 hexadecimal digest safe to persist in the local ledger.
    """

    return hashlib.sha256(token.encode("utf-8")).hexdigest()
