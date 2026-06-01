"""JavaScript-enabled scraper using Playwright."""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import nest_asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel, Field

from tools.registry import get_registry

logger = logging.getLogger(__name__)


class ScrapeJsInput(BaseModel):
    """Input schema for scrape_js tool."""
    url: str = Field(..., description="URL of the page to scrape")
    wait_for_selector: str = Field(
        default=".coupon-code",
        description="CSS selector to wait for before extracting content"
    )
    timeout_seconds: int = Field(default=30, description="Playwright timeout in seconds")
    merchant_id: Optional[str] = Field(default=None, description="Merchant ID for file naming")


class ScrapeJsOutput(BaseModel):
    """Output schema for scrape_js tool."""
    html: Optional[str] = None
    page_title: Optional[str] = None
    status_code: int = 0
    saved_path: Optional[str] = None
    error_type: Optional[str] = None


def scrape_js(
    url: str,
    wait_for_selector: str = ".coupon-code",
    timeout_seconds: int = 30,
    merchant_id: Optional[str] = None,
) -> dict:
    """Scrape JavaScript-rendered content using Playwright."""
    logger.info(f"Scraping {url} with Playwright (waiting for '{wait_for_selector}')")
    
    try:
        # Run async scraper
        nest_asyncio.apply()
        result = asyncio.run(
            _scrape_js_async(
                url=url,
                wait_for_selector=wait_for_selector,
                timeout_seconds=timeout_seconds,
                merchant_id=merchant_id,
            )
        )
        return result
    
    except Exception as e:
        logger.error(f"Playwright scraping failed: {e}")
        return {
            "html": None,
            "page_title": None,
            "status_code": 0,
            "saved_path": None,
            "error_type": "PERMANENT",
        }


async def _scrape_js_async(
    url: str,
    wait_for_selector: str,
    timeout_seconds: int,
    merchant_id: Optional[str],
) -> dict:
    """Async implementation of JS scraping with Playwright."""
    playwright = None
    browser = None
    page = None
    
    try:
        playwright = await async_playwright().start()
        
        # Launch chromium browser
        logger.info("Launching Playwright browser")
        browser = await playwright.chromium.launch(headless=True)
        
        # Create new page
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = await context.new_page()
        
        # Set timeout
        page.set_default_timeout(timeout_seconds * 1000)  # ms
        
        # Navigate to URL
        logger.info(f"Navigating to {url}")
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        
        if response is None or response.status != 200:
            status_code = response.status if response else 0
            logger.warning(f"Navigation failed: status {status_code}")
            return {
                "html": None,
                "page_title": None,
                "status_code": status_code,
                "saved_path": None,
                "error_type": "TRANSIENT" if status_code >= 500 else "NOT_FOUND",
            }
        
        # Wait for selector to appear
        try:
            logger.info(f"Waiting for selector '{wait_for_selector}'")
            await page.wait_for_selector(wait_for_selector, timeout=timeout_seconds * 1000)
            logger.info(f"Selector found: {wait_for_selector}")
        except PlaywrightTimeoutError:
            logger.warning(f"Timeout waiting for selector '{wait_for_selector}'")
            # Continue anyway - get whatever content is there
        
        # Get page content
        html = await page.content()
        
        # Extract page title
        page_title = await page.title()
        
        # Save HTML
        saved_path = None
        try:
            scraped_dir = Path("data/scraped")
            scraped_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename_prefix = merchant_id or "unknown"
            filename = f"{filename_prefix}_js_{timestamp}.html"
            saved_path = str(scraped_dir / filename)
            
            Path(saved_path).write_text(html, encoding="utf-8")
            logger.info(f"Saved JS-rendered HTML to {saved_path}")
        except Exception as e:
            logger.warning(f"Could not save HTML: {e}")
        
        logger.info(f"JS scraping succeeded for {url}")
        return {
            "html": html,
            "page_title": page_title,
            "status_code": 200,
            "saved_path": saved_path,
            "error_type": None,
        }
    
    except PlaywrightTimeoutError as e:
        logger.error(f"Playwright timeout: {e}")
        return {
            "html": None,
            "page_title": None,
            "status_code": 0,
            "saved_path": None,
            "error_type": "TIMEOUT",
        }
    
    except Exception as e:
        logger.error(f"Playwright error: {e}")
        
        # Classify error type
        error_msg = str(e).lower()
        if "timeout" in error_msg:
            error_type = "TIMEOUT"
        elif "404" in error_msg or "not found" in error_msg:
            error_type = "NOT_FOUND"
        elif "connection" in error_msg:
            error_type = "TRANSIENT"
        else:
            error_type = "PERMANENT"
        
        return {
            "html": None,
            "page_title": None,
            "status_code": 0,
            "saved_path": None,
            "error_type": error_type,
        }
    
    finally:
        # Clean up
        if page:
            try:
                await page.close()
            except Exception as e:
                logger.warning(f"Error closing page: {e}")
        
        if browser:
            try:
                await browser.close()
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")
        
        if playwright:
            try:
                await playwright.stop()
            except Exception as e:
                logger.warning(f"Error stopping playwright: {e}")


# Register the tool
registry = get_registry()
registry.register(
    name="scrape_js",
    description="Scrape JavaScript-rendered content using Playwright (fallback for dynamic pages)",
    timeout_seconds=60,  # Longer timeout for browser operations
    cost_annotation="MEDIUM",
    schema=ScrapeJsInput,
)(scrape_js)
