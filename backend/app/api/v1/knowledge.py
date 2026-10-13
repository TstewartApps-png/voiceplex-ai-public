"""
Knowledge Base API endpoints.

Provides endpoints for scraping websites and managing knowledge base content.
"""

import logging
import ipaddress
import re
import socket
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl

from app.api.deps import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["Knowledge"])


class ScrapeRequest(BaseModel):
    """Request to scrape a website URL."""

    url: HttpUrl = Field(..., description="URL to scrape")


class ScrapeResponse(BaseModel):
    """Response from website scraping."""

    title: str = Field(..., description="Page title")
    content: str = Field(..., description="Extracted text content")
    url: str = Field(..., description="Source URL")


def clean_text(text: str) -> str:
    """Clean extracted text by removing extra whitespace."""
    # Remove multiple spaces/newlines
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def extract_title_from_html(html: str) -> str:
    """Extract title from HTML content."""
    # Simple regex to get title
    title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
    if title_match:
        return title_match.group(1).strip()
    return ""


def extract_text_from_html(html: str) -> str:
    """
    Extract readable text from HTML content.

    This is a basic implementation. For production, consider using
    libraries like BeautifulSoup, lxml, or trafilatura for better extraction.
    """
    # Remove script and style elements
    html = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<noscript[^>]*>[\s\S]*?</noscript>', '', html, flags=re.IGNORECASE)

    # Remove HTML comments
    html = re.sub(r'<!--[\s\S]*?-->', '', html)

    # Remove head section
    html = re.sub(r'<head[^>]*>[\s\S]*?</head>', '', html, flags=re.IGNORECASE)

    # Remove nav, footer, header (often not useful content)
    html = re.sub(r'<nav[^>]*>[\s\S]*?</nav>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<footer[^>]*>[\s\S]*?</footer>', '', html, flags=re.IGNORECASE)

    # Convert common elements to text with spacing
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</(p|div|h[1-6]|li|tr)>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<(p|div|h[1-6]|li|tr)[^>]*>', '\n', html, flags=re.IGNORECASE)

    # Remove remaining HTML tags
    html = re.sub(r'<[^>]+>', ' ', html)

    # Decode common HTML entities
    html = html.replace('&nbsp;', ' ')
    html = html.replace('&amp;', '&')
    html = html.replace('&lt;', '<')
    html = html.replace('&gt;', '>')
    html = html.replace('&quot;', '"')
    html = html.replace('&#39;', "'")
    html = html.replace('&apos;', "'")

    return clean_text(html)


def _is_public_host(hostname: str) -> bool:
    """
    SSRF guard: resolve the host and refuse anything that is not a public
    unicast address (loopback, RFC1918, link-local incl. 169.254.169.254 cloud
    metadata, multicast, reserved, ...).
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            return False
    return True


def _assert_safe_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only HTTP and HTTPS URLs are supported",
        )
    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URLs with embedded credentials are not allowed",
        )
    host = parsed.hostname or ""
    if not host or host == "localhost" or host.endswith(".localhost") or not _is_public_host(host):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only publicly reachable hosts can be scraped",
        )


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_website(
    request: ScrapeRequest,
    current_user: CurrentUser,
) -> ScrapeResponse:
    """
    Scrape content from a website URL.

    Extracts the page title and main text content for use in the knowledge base.

    Note: This is a basic implementation. For production use, consider:
    - Using a headless browser for JavaScript-rendered content
    - Implementing rate limiting
    - Adding caching
    - Using specialized libraries like trafilatura
    """
    url_str = str(request.url)
    parsed = urlparse(url_str)

    # Validate URL (scheme + SSRF guard on the initial host)
    _assert_safe_url(url_str)

    try:
        import httpx

        async with httpx.AsyncClient(
            follow_redirects=False,  # redirects are followed manually so each hop passes the SSRF guard
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; VoicePlex/1.0; +https://voiceplex.ai)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
        ) as client:
            response = await client.get(url_str)
            hops = 0
            while response.is_redirect and hops < 5:
                next_url = str(response.next_request.url) if response.next_request else ""
                if not next_url:
                    break
                _assert_safe_url(next_url)
                response = await client.get(next_url)
                hops += 1
            response.raise_for_status()

            # Check content type
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"URL does not return HTML content (got {content_type})",
                )

            html = response.text

    except httpx.HTTPStatusError as e:
        logger.warning(f"HTTP error scraping {url_str}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch URL: HTTP {e.response.status_code}",
        )
    except httpx.TimeoutException:
        logger.warning(f"Timeout scraping {url_str}")
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail="Request timed out. The website may be slow or unavailable.",
        )
    except httpx.RequestError as e:
        logger.error(f"Request error scraping {url_str}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch URL: {str(e)}",
        )

    # Extract content
    title = extract_title_from_html(html) or parsed.netloc
    content = extract_text_from_html(html)

    if not content or len(content) < 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not extract meaningful content from the page. It may be JavaScript-rendered or blocked.",
        )

    # Limit content length (knowledge base items shouldn't be too large)
    max_content_length = 50000
    if len(content) > max_content_length:
        content = content[:max_content_length] + "\n\n[Content truncated...]"

    logger.info(f"Scraped {url_str} for user {current_user.id}: {len(content)} chars")

    return ScrapeResponse(
        title=title,
        content=content,
        url=url_str,
    )
