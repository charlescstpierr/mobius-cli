"""Readable identifier helpers for user-facing Mobius sessions."""

from __future__ import annotations

import re
import unicodedata
import uuid

MAX_SLUG_LENGTH = 36


def readable_session_id(prefix: str, label: str) -> str:
    """Return a unique, human-readable session id.

    The stable shape keeps existing command routing simple while making the
    middle segment meaningful in logs and status output.
    """
    slug = slugify(label) or "session"
    suffix = uuid.uuid4().hex[:8]
    return f"{prefix}_{slug}_{suffix}"


def slugify(value: str) -> str:
    """Convert arbitrary user/spec text into a compact ASCII slug."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) <= MAX_SLUG_LENGTH:
        return slug
    trimmed = slug[:MAX_SLUG_LENGTH].rstrip("-")
    if "-" not in trimmed:
        return trimmed
    return trimmed.rsplit("-", 1)[0] or trimmed
