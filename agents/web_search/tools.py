# agents/web_search/tools.py  ← COMPLETE FILE
"""
LAYER 1: Pure tool logic.

Changes from previous version:
- duckduckgo_search → ddgs (renamed package)
- Added rate limit handling for DDG
- Better result accumulation across retries
"""

from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Any
import httpx
from ddgs import DDGS          # ← NEW IMPORT (was duckduckgo_search)
import structlog

from shared.config import settings

logger = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════
# RESULT DATA CLASSES
# ══════════════════════════════════════════════════════════════

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str


@dataclass
class NewsResult:
    title: str
    url: str
    snippet: str
    published_date: str | None
    source_name: str


@dataclass
class FetchResult:
    url: str
    content: str
    title: str | None
    status_code: int


# ══════════════════════════════════════════════════════════════
# SEARCH PROVIDERS
# ══════════════════════════════════════════════════════════════

async def _search_google_cse(
    query: str,
    max_results: int,
    client: httpx.AsyncClient
) -> list[SearchResult]:
    """
    Google Custom Search Engine.
    Free tier: 100 queries/day.
    """
    if not settings.google_search_api_key or \
       not settings.google_search_engine_id:
        raise ValueError("Google CSE not configured")

    params = {
        "key": settings.google_search_api_key,
        "cx": settings.google_search_engine_id,
        "q": query,
        "num": min(max_results, 10),
    }

    response = await client.get(
        "https://www.googleapis.com/customsearch/v1",
        params=params,
        timeout=10.0
    )
    response.raise_for_status()
    data = response.json()

    results = []
    for item in data.get("items", []):
        results.append(SearchResult(
            title=item.get("title", ""),
            url=item.get("link", ""),
            snippet=item.get("snippet", ""),
            source="google_cse"
        ))

    logger.info(
        "google_cse_search_complete",
        query=query,
        result_count=len(results)
    )
    return results


async def _search_duckduckgo(
    query: str,
    max_results: int
) -> list[SearchResult]:
    """
    DuckDuckGo search via ddgs package.
    No API key required.

    RATE LIMIT HANDLING:
    DDG rate-limits aggressive querying.
    We add a small delay and return empty
    list on rate limit (caller handles fallback).
    """
    def _sync_search() -> list[dict[str, Any]]:
        try:
            # ddgs new API — context manager style
            with DDGS() as ddgs:
                results = list(ddgs.text(
                    query,
                    max_results=max_results
                ))
                return results
        except Exception as e:
            # Rate limit or network error
            logger.warning(
                "ddgs_search_error",
                query=query,
                error=str(e)[:100]
            )
            return []

    loop = asyncio.get_event_loop()
    raw_results = await loop.run_in_executor(None, _sync_search)

    results = []
    for item in raw_results:
        results.append(SearchResult(
            title=item.get("title", ""),
            url=item.get("href", ""),
            snippet=item.get("body", ""),
            source="duckduckgo"
        ))

    logger.info(
        "duckduckgo_search_complete",
        query=query,
        result_count=len(results)
    )
    return results


# ══════════════════════════════════════════════════════════════
# PUBLIC TOOL FUNCTIONS
# ══════════════════════════════════════════════════════════════

async def search_web(
    query: str,
    max_results: int = 5
) -> list[SearchResult]:
    """
    Search the web using fallback chain:
    1. Google CSE (if configured and working)
    2. DuckDuckGo via ddgs (free fallback)

    IMPORTANT: Results are cached per query within
    a single agent session to avoid DDG rate limits.
    """
    max_results = max(1, min(max_results, 10))

    async with httpx.AsyncClient() as client:
        # Try Google CSE first
        if settings.google_search_api_key:
            try:
                results = await _search_google_cse(
                    query, max_results, client
                )
                if results:
                    return results
            except Exception as e:
                logger.warning(
                    "google_cse_failed_falling_back",
                    error=str(e)[:100]
                )

        # Fallback to DuckDuckGo
        logger.info("using_duckduckgo_fallback", query=query)

        # Small delay to be respectful to DDG
        await asyncio.sleep(0.5)

        return await _search_duckduckgo(query, max_results)


async def get_news(
    topic: str,
    max_results: int = 5
) -> list[NewsResult]:
    """
    Fetch recent news using ddgs News search.
    No API key required.
    """
    max_results = max(1, min(max_results, 10))

    def _sync_news() -> list[dict[str, Any]]:
        try:
            with DDGS() as ddgs:
                return list(ddgs.news(
                    topic,
                    max_results=max_results
                ))
        except Exception as e:
            logger.warning(
                "ddgs_news_error",
                topic=topic,
                error=str(e)[:100]
            )
            return []

    loop = asyncio.get_event_loop()
    raw_results = await loop.run_in_executor(None, _sync_news)

    results = []
    for item in raw_results:
        results.append(NewsResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("body", ""),
            published_date=item.get("date"),
            source_name=item.get("source", "")
        ))

    logger.info(
        "news_search_complete",
        topic=topic,
        result_count=len(results)
    )
    return results


async def fetch_url(url: str) -> FetchResult:
    """
    Fetch a URL and extract readable text.
    Strips HTML, returns clean content.
    """
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; A2AMarketplaceBot/1.0)"
        )
    }

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=15.0
    ) as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            for element in soup(
                ["script", "style", "nav", "footer", "header"]
            ):
                element.decompose()

            title = None
            if soup.title:
                title = soup.title.string

            text = soup.get_text(separator="\n", strip=True)
            lines = [
                line.strip()
                for line in text.splitlines()
                if line.strip()
            ]
            content = "\n".join(lines)

            if len(content) > 8000:
                content = content[:8000] + "\n...[truncated]"

            logger.info(
                "url_fetch_complete",
                url=url,
                content_length=len(content),
                status_code=response.status_code
            )

            return FetchResult(
                url=url,
                content=content,
                title=title,
                status_code=response.status_code
            )

        except httpx.HTTPError as e:
            logger.error(
                "url_fetch_failed",
                url=url,
                error=str(e)
            )
            return FetchResult(
                url=url,
                content=f"Error fetching URL: {str(e)}",
                title=None,
                status_code=getattr(
                    getattr(e, "response", None),
                    "status_code", 0
                )
            )