"""Thin client for Component 1's live API — the meeting-transcript pipeline
that produces requirements and user stories, grouped by iteration.

RTM has no local link to Component 1's iterations, so the RTM Matrix page
asks for one explicitly (a manual "Iteration ID" field) and this module
fetches that iteration's requirements+stories directly, the same pattern
used for Component 2 in integrations/component2.py.
"""

import os

import httpx

COMPONENT1_API_URL = os.getenv("COMPONENT1_API_URL", "http://localhost:8001")
_TIMEOUT = 5.0


class Component1Unavailable(Exception):
    """Raised when Component 1's API can't be reached or returns an error."""


async def _get(path: str, params: dict | None = None):
    url = f"{COMPONENT1_API_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        raise Component1Unavailable(f"Component 1 request failed ({url}): {e}") from e


async def get_requirements_with_stories(iteration_id: str) -> list[dict]:
    # Real mount path (confirmed from source): user_stories_router is included
    # with prefix "/api/v1/pipeline" in Component 1's main.py. The endpoint
    # itself wraps the list as {iteration_id, total, items: [...]}.
    data = await _get(f"/api/v1/pipeline/iterations/{iteration_id}/requirements-with-stories")
    return data.get("items", [])
