"""Looking a place up in the outside world (Issue 38).

Enrichment has meant "from the user's other memories" until now — that is what
the Enrichment Agent does. This is the other direction: facts from outside the
app, held separately and labelled with where they came from, so a user can
always tell what they said from what was found.

Places only. Resolving a person's name to a real individual is unreliable *and*
invasive, and being helpfully wrong about a friend is worse than saying nothing.

Only the search half is here. Fetching the entity's actual claims — founded,
dissolved, located in — is the next step, and deliberately separate so the
match can be judged before anything is stored from it.
"""

from dataclasses import dataclass
from typing import Optional

import httpx

WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_ENTITY_URL = "http://www.wikidata.org/entity/"
REQUEST_TIMEOUT_SECONDS = 20.0
SEARCH_LIMIT = 5

# Wikidata asks automated clients to identify themselves, and will throttle
# anonymous ones.
USER_AGENT = "MEMIND/0.1 (personal memory app; place lookup)"


@dataclass(frozen=True)
class PlaceMatch:
    """What a lookup found, and where it found it.

    The label and description travel with the match on purpose: they are how a
    person can tell whether the match is the place they meant.
    """

    source: str
    source_id: str
    label: str
    description: Optional[str]
    url: str


async def _search(name: str, limit: int) -> list[dict]:
    """Ask Wikidata for candidate entities matching a name."""
    params = {
        "action": "wbsearchentities",
        "search": name,
        "language": "en",
        "uselang": "en",
        "format": "json",
        "limit": limit,
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(
            WIKIDATA_API_URL,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json().get("search", [])


def _to_match(candidate: dict) -> Optional[PlaceMatch]:
    """Turn a search result into a match, or discard it if unusable."""
    source_id = candidate.get("id")
    label = candidate.get("label")
    if not source_id or not label:
        return None

    return PlaceMatch(
        source="wikidata",
        source_id=source_id,
        label=str(label),
        description=candidate.get("description") or None,
        url=f"{WIKIDATA_ENTITY_URL}{source_id}",
    )


async def find_place(name: str) -> Optional[PlaceMatch]:
    """The best match for a place's name, or None if there is none.

    The first usable result, deliberately. The caller shows what was matched —
    label and description alike — so a wrong match is visible rather than
    silent, which is the honest way to start before letting the user choose
    between candidates.
    """
    if not name or not name.strip():
        return None

    for candidate in await _search(name.strip(), SEARCH_LIMIT):
        match = _to_match(candidate)
        if match is not None:
            return match

    return None
