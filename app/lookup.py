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

A place is often described with a generic type word — "Mission Valley Theater"
— while the source names it another way — "Mission Valley Cinemas". Searching
the wording verbatim misses it, so a name that finds nothing useful is
broadened by dropping that word and trying again.
"""

import re
from dataclasses import dataclass
from typing import Optional

import httpx

WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_ENTITY_URL = "http://www.wikidata.org/entity/"
REQUEST_TIMEOUT_SECONDS = 20.0
SEARCH_LIMIT = 5

# Generic venue words carry little identifying power, and they are exactly
# where a name-against-index search fails: Wikidata does not retrieve
# "Mission Valley Cinemas" for "Mission Valley Theater", but it retrieves it
# for "Mission Valley". Dropping them is the fallback that closes the gap. The
# list is deliberately short and concrete — every word here is one that rarely
# distinguishes one place from another.
GENERIC_PLACE_WORDS = frozenset(
    {
        "theater", "theatre", "cinema", "cinemas", "movie",
        "mall", "cafe", "café", "restaurant", "bar", "club", "pub",
        "church", "school", "park", "stadium", "arena", "hotel", "motel",
        "store", "shop", "market", "museum", "library", "hospital",
        "airport", "beach", "bridge", "tower", "plaza", "center", "centre",
        "hall", "garden", "gardens", "cemetery", "ballroom", "lounge",
        "diner", "grill", "bistro", "saloon",
    }
)

# Articles and connectives that never identify a place on their own.
STOPWORDS = frozenset(
    {"the", "a", "an", "of", "and", "at", "in", "on", "de", "la", "le", "el"}
)

# Case-preserving: _tokens lowercases before matching, while _broaden keeps the
# original wording to build a query from. A lowercase-only class would silently
# split "Theater" into "heater".
_WORD = re.compile(r"[A-Za-z0-9]+")

# Wikidata asks automated clients to identify themselves, and will throttle
# anonymous ones.
USER_AGENT = "Tapestry/0.1 (personal memory app; place lookup)"


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


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _distinctive_tokens(name: str) -> list[str]:
    """The words in a place's name that might actually identify it."""
    return [
        token
        for token in _tokens(name)
        if token not in GENERIC_PLACE_WORDS and token not in STOPWORDS
    ]


def _broaden(name: str) -> Optional[str]:
    """The name with its generic venue words removed, or None if none drop.

    "Mission Valley Theater" broadens to "Mission Valley"; "Raleigh" has
    nothing to drop and broadens to nothing.
    """
    words = _WORD.findall(name)
    kept = [word for word in words if word.lower() not in GENERIC_PLACE_WORDS]
    if not kept or len(kept) == len(words):
        return None
    return " ".join(kept)


def _matches(candidates: list[dict]) -> list[PlaceMatch]:
    """Turn search results into matches, discarding any that are unusable."""
    matches: list[PlaceMatch] = []
    for candidate in candidates:
        match = _to_match(candidate)
        if match is not None:
            matches.append(match)
    return matches


def _looks_relevant(name: str, match: PlaceMatch) -> bool:
    """Whether a candidate shares an identifying word with the name.

    When the name has no identifying word left, there is nothing to judge by,
    so whatever the search returned is accepted rather than discarded.
    """
    distinctive = _distinctive_tokens(name)
    if not distinctive:
        return True
    label_tokens = set(_tokens(match.label))
    return any(token in label_tokens for token in distinctive)


async def search_places(name: str, limit: int = 3) -> list[PlaceMatch]:
    """Candidate places matching a name, best first.

    Several, not one. "Raleigh" returns a city, a family name and an Australian
    electorate; "Bluebird Cafe" returns a Nashville music club and a Californian
    restaurant. Choosing between them is the user's job, and the label and
    description are what make that choice possible.

    The name is searched as written first, and only broadened — the generic
    venue word dropped — when the exact wording finds nothing that shares an
    identifying word. The results already in hand are kept if the broader
    search does no better.
    """
    if not name or not name.strip():
        return []

    name = name.strip()
    api_limit = max(limit, SEARCH_LIMIT)
    direct = _matches(await _search(name, api_limit))
    if any(_looks_relevant(name, match) for match in direct):
        return direct[:limit]

    broader = _broaden(name)
    if broader:
        widened = _matches(await _search(broader, api_limit))
        relevant = [match for match in widened if _looks_relevant(name, match)]
        if relevant:
            return relevant[:limit]

    return direct[:limit]


async def find_place(name: str) -> Optional[PlaceMatch]:
    """The single best match for a place's name, or None if there is none."""
    matches = await search_places(name, limit=1)
    return matches[0] if matches else None
