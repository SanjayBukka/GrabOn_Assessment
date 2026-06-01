"""HTML scraper tool for GrabOn deal pages."""

import asyncio
import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from pydantic import BaseModel, Field

from tools.registry import get_registry

logger = logging.getLogger(__name__)


class ScrapeHtmlInput(BaseModel):
    """Input schema for scrape_html tool."""
    url: str = Field(..., description="URL of the page to scrape")
    timeout_seconds: int = Field(default=10, description="HTTP timeout in seconds")
    delay_before: float = Field(default=2.0, description="Seconds to wait before scraping")
    merchant_id: Optional[str] = Field(default=None, description="Merchant ID for file naming")


class ScrapeHtmlOutput(BaseModel):
    """Output schema for scrape_html tool."""
    html: Optional[str] = None
    page_title: Optional[str] = None
    status_code: int = 0
    saved_path: Optional[str] = None
    error_type: Optional[str] = None


# User-Agent rotation list
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
]


def scrape_html(
    url: str,
    timeout_seconds: int = 10,
    delay_before: float = 2.0,
    merchant_id: Optional[str] = None,
) -> dict:
    """Scrape HTML from a URL using httpx."""
    logger.info(f"Scraping {url} (delay={delay_before}s, timeout={timeout_seconds}s)")
    
    # Wait before scraping
    if delay_before > 0:
        time.sleep(delay_before)
    
    # Pick random User-Agent
    user_agent = random.choice(USER_AGENTS)
    headers = {"User-Agent": user_agent}
    
    try:
        # Make HTTP request
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.get(url, headers=headers, follow_redirects=True)
        
        # Handle status codes
        if response.status_code == 200:
            html = response.text
            
            # Extract page title
            page_title = None
            if "<title>" in html:
                start = html.find("<title>") + 7
                end = html.find("</title>")
                if end > start:
                    page_title = html[start:end].strip()
            
            # Save HTML to data/scraped/
            saved_path = None
            try:
                scraped_dir = Path("data/scraped")
                scraped_dir.mkdir(parents=True, exist_ok=True)
                
                # Create filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename_prefix = merchant_id or "unknown"
                filename = f"{filename_prefix}_{timestamp}.html"
                saved_path = str(scraped_dir / filename)
                
                # Save file
                Path(saved_path).write_text(html, encoding="utf-8")
                logger.info(f"Saved HTML to {saved_path}")
            except Exception as e:
                logger.warning(f"Could not save HTML: {e}")
            
            return {
                "html": html,
                "page_title": page_title,
                "status_code": 200,
                "saved_path": saved_path,
                "error_type": None,
            }
        
        elif response.status_code == 404:
            logger.warning(f"Page not found: {url} (404)")
            return {
                "html": None,
                "page_title": None,
                "status_code": 404,
                "saved_path": None,
                "error_type": "NOT_FOUND",
            }
        
        elif response.status_code in (403, 429):
            logger.warning(f"Rate limited or forbidden: {url} ({response.status_code})")
            return {
                "html": None,
                "page_title": None,
                "status_code": response.status_code,
                "saved_path": None,
                "error_type": "RATE_LIMIT",
            }
        
        else:
            logger.warning(f"Unexpected status code: {response.status_code}")
            return {
                "html": None,
                "page_title": None,
                "status_code": response.status_code,
                "saved_path": None,
                "error_type": "TRANSIENT",
            }
    
    except httpx.TimeoutException as e:
        logger.error(f"Request timed out: {url}")
        return {
            "html": None,
            "page_title": None,
            "status_code": 0,
            "saved_path": None,
            "error_type": "TIMEOUT",
        }
    
    except httpx.ConnectError as e:
        logger.error(f"Connection error: {e}")
        return {
            "html": None,
            "page_title": None,
            "status_code": 0,
            "saved_path": None,
            "error_type": "TRANSIENT",
        }
    
    except Exception as e:
        logger.error(f"Unexpected error during scraping: {e}")
        return {
            "html": None,
            "page_title": None,
            "status_code": 0,
            "saved_path": None,
            "error_type": "PERMANENT",
        }


# Register the tool
registry = get_registry()
registry.register(
    name="scrape_html",
    description="Scrape raw HTML from a GrabOn deal page using httpx",
    timeout_seconds=30,
    cost_annotation="LOW",
    schema=ScrapeHtmlInput,
)(scrape_html)
