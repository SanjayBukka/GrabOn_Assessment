"""
Google Cache and Bing Cache fallback scraper.

Fetches cached versions of pages when direct scraping is blocked.
Tries Google Cache first, then falls back to Bing Cache.
"""

import logging
import random
import time
from typing import Optional
from pathlib import Path
from datetime import datetime

import httpx
from pydantic import BaseModel, Field

from tools.registry import get_registry

logger = logging.getLogger(__name__)


class GoogleCacheInput(BaseModel):
    """Input schema for google_cache tool."""
    original_url: str = Field(..., description="Original URL to fetch from cache")
    timeout_seconds: int = Field(default=15, description="HTTP timeout in seconds")
    merchant_id: Optional[str] = Field(default=None, description="Merchant ID for file naming")


class GoogleCacheOutput(BaseModel):
    """Output schema for google_cache tool."""
    html: Optional[str] = None
    page_title: Optional[str] = None
    status_code: int = 0
    saved_path: Optional[str] = None
    cache_source: Optional[str] = None  # "google" or "bing"
    error_type: Optional[str] = None


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
]


def google_cache(
    original_url: str,
    timeout_seconds: int = 15,
    merchant_id: Optional[str] = None,
) -> dict:
    """
    Fetch cached version of page from Google Cache or Bing Cache.
    
    Args:
        original_url: Original URL to fetch from cache
        timeout_seconds: HTTP timeout in seconds
        merchant_id: Optional merchant ID for file naming
    
    Returns:
        Dictionary with html, page_title, status_code, saved_path, cache_source, error_type
    """
    logger.info(f"Attempting Google Cache for {original_url}")
    
    user_agent = random.choice(USER_AGENTS)
    headers = {"User-Agent": user_agent}
    
    # Try Google Cache first
    google_cache_url = f"https://webcache.googleusercontent.com/cache:{original_url}"
    result = _try_cache_source(google_cache_url, "google", headers, timeout_seconds, merchant_id)
    
    if result["error_type"] is None:
        return result
    
    # Fall back to Bing Cache
    logger.warning(f"Google Cache failed, trying Bing Cache for {original_url}")
    bing_cache_url = f"https://cc.bingj.com/cache.aspx?q={original_url}"
    result = _try_cache_source(bing_cache_url, "bing", headers, timeout_seconds, merchant_id)
    
    return result


def _try_cache_source(
    cache_url: str,
    source_name: str,
    headers: dict,
    timeout_seconds: int,
    merchant_id: Optional[str],
) -> dict:
    """
    Try a single cache source (Google or Bing).
    
    Args:
        cache_url: URL to the cache service
        source_name: "google" or "bing"
        headers: HTTP headers with User-Agent
        timeout_seconds: HTTP timeout
        merchant_id: Optional merchant ID
    
    Returns:
        Result dictionary
    """
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.get(cache_url, headers=headers, follow_redirects=True)
        
        if response.status_code == 200:
            html = response.text
            
            # Strip cache service headers if present
            if "<!-- This is the cache of" in html:
                # Remove Google Cache header
                end_idx = html.find("-->", html.find("<!-- This is the cache of")) + 3
                if end_idx > 3:
                    html = html[end_idx:]
            
            # Extract page title
            page_title = None
            if "<title>" in html:
                start = html.find("<title>") + 7
                end = html.find("</title>")
                if end > start:
                    page_title = html[start:end].strip()
            
            # Save HTML
            saved_path = None
            try:
                scraped_dir = Path("data/scraped")
                scraped_dir.mkdir(parents=True, exist_ok=True)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename_prefix = merchant_id or "unknown"
                filename = f"{filename_prefix}_{source_name}_cache_{timestamp}.html"
                saved_path = str(scraped_dir / filename)
                
                Path(saved_path).write_text(html, encoding="utf-8")
                logger.info(f"Saved {source_name} cache HTML to {saved_path}")
            except Exception as e:
                logger.warning(f"Could not save cache HTML: {e}")
            
            logger.info(f"{source_name.capitalize()} Cache succeeded")
            return {
                "html": html,
                "page_title": page_title,
                "status_code": 200,
                "saved_path": saved_path,
                "cache_source": source_name,
                "error_type": None,
            }
        
        elif response.status_code == 404:
            logger.warning(f"{source_name.capitalize()} Cache: page not found")
            return {
                "html": None,
                "page_title": None,
                "status_code": 404,
                "saved_path": None,
                "cache_source": source_name,
                "error_type": "NOT_FOUND",
            }
        
        elif response.status_code in (403, 429):
            logger.warning(f"{source_name.capitalize()} Cache: rate limited")
            return {
                "html": None,
                "page_title": None,
                "status_code": response.status_code,
                "saved_path": None,
                "cache_source": source_name,
                "error_type": "RATE_LIMIT",
            }
        
        else:
            logger.warning(f"{source_name.capitalize()} Cache: status {response.status_code}")
            return {
                "html": None,
                "page_title": None,
                "status_code": response.status_code,
                "saved_path": None,
                "cache_source": source_name,
                "error_type": "TRANSIENT",
            }
    
    except httpx.TimeoutException:
        logger.error(f"{source_name.capitalize()} Cache: timeout")
        return {
            "html": None,
            "page_title": None,
            "status_code": 0,
            "saved_path": None,
            "cache_source": source_name,
            "error_type": "TIMEOUT",
        }
    
    except httpx.ConnectError as e:
        logger.error(f"{source_name.capitalize()} Cache: connection error")
        return {
            "html": None,
            "page_title": None,
            "status_code": 0,
            "saved_path": None,
            "cache_source": source_name,
            "error_type": "TRANSIENT",
        }
    
    except Exception as e:
        logger.error(f"{source_name.capitalize()} Cache: unexpected error: {e}")
        return {
            "html": None,
            "page_title": None,
            "status_code": 0,
            "saved_path": None,
            "cache_source": source_name,
            "error_type": "PERMANENT",
        }


# Register the tool
registry = get_registry()
registry.register(
    name="google_cache",
    description="Fetch cached version of page from Google Cache or Bing Cache (fallback when direct scraping fails)",
    timeout_seconds=30,
    cost_annotation="LOW",
    schema=GoogleCacheInput,
)(google_cache)
