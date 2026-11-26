"""Bounded Exa web search adapter. Search results are untrusted source material."""
from urllib.parse import urlsplit

import httpx


ENDPOINT = "https://api.exa.ai/search"
MAX_QUERY_CHARS = 500
MAX_RESULTS = 5


def validate_query(value: str) -> str:
    query = " ".join(value.split())
    if not query or len(query) > MAX_QUERY_CHARS:
        raise ValueError("Search query must contain 1 to 500 characters")
    if any(ord(char) < 32 for char in query):
        raise ValueError("Search query contains unsupported control characters")
    return query


def normalize_results(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("Exa returned an invalid search response")
    normalized = []
    for row in payload["results"][:MAX_RESULTS]:
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        if not isinstance(url, str):
            continue
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            continue
        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            title = parsed.hostname
        raw_highlights = row.get("highlights")
        highlights = [item.strip()[:800] for item in raw_highlights[:2]
                      if isinstance(item, str) and item.strip()] if isinstance(raw_highlights, list) else []
        published = row.get("publishedDate")
        normalized.append({
            "title": title.strip()[:240],
            "url": url[:1500],
            "author": str(row.get("author") or "")[:160] or None,
            "published_at": str(published)[:64] if published else None,
            "highlights": highlights,
            "source": "Exa",
            "untrusted": True,
        })
    return normalized


async def search(client: httpx.AsyncClient, api_key: str, query: str) -> list[dict]:
    query = validate_query(query)
    response = await client.post(
        ENDPOINT,
        headers={"x-api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"},
        json={"query": query, "type": "auto", "numResults": MAX_RESULTS,
              "contents": {"highlights": True}},
    )
    response.raise_for_status()
    return normalize_results(response.json())
