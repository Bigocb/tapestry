"""Privacy helpers for locked (private) memories.

A private memory's content is withheld from every API response unless the
client explicitly presents its id in the ``X-Unlocked-Memory-Ids`` header for
that session. Unlocking is therefore per-session and never persisted, so
locked content does not survive a page reload.

This is a *shoulder-surfing* shield, not an authorisation boundary: any
authenticated user of the account can unlock anything, because the lock is
about hiding content on screen, not about separating users.
"""

from typing import Iterable, Set

from fastapi import Header

UNLOCK_HEADER = "X-Unlocked-Memory-Ids"
LOCKED_TITLE = "Private memory"
LOCKED_SUMMARY = "This memory is locked. Unlock it to see its contents."


def get_unlocked_memory_ids(
    x_unlocked_memory_ids: str | None = Header(
        default=None,
        alias=UNLOCK_HEADER,
        description="Comma-separated memory ids the client has unlocked this session.",
    ),
) -> Set[str]:
    """Parse the unlock header into a set of memory ids."""
    if not x_unlocked_memory_ids:
        return set()
    return {
        token.strip()
        for token in x_unlocked_memory_ids.split(",")
        if token.strip()
    }


def is_locked(memory, unlocked_ids: Iterable[str]) -> bool:
    """Return True if ``memory`` is private and not unlocked."""
    if not getattr(memory, "is_private", False):
        return False
    return str(memory.id) not in set(unlocked_ids)
