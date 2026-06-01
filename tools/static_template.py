"""
Static template fallback tool.

Builds deterministic HTML from the mock database when live scraping fails.
This keeps the audit pipeline moving without relying on search-engine caches.
"""

import json
import logging
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from tools.registry import get_registry

logger = logging.getLogger(__name__)


class StaticTemplateInput(BaseModel):
    """Input schema for static_template tool."""
    merchant_id: str = Field(..., description="Merchant ID")
    merchant_name: str = Field(..., description="Merchant name")


class StaticTemplateOutput(BaseModel):
    """Output schema for static_template tool."""
    html: str = ""
    page_title: str = ""
    status_code: int = 200
    saved_path: Optional[str] = None
    template_source: str = "mock_db"
    error_type: Optional[str] = None


def static_template(merchant_id: str, merchant_name: str) -> dict:
    """
    Generate a static coupon-page template from mock DB deals.

    Args:
        merchant_id: Merchant ID to load from mock DB
        merchant_name: Display name for the generated page

    Returns:
        Dictionary matching scraper output shape with HTML and metadata
    """
    logger.info(f"Generating static fallback template for {merchant_name}")

    db_path = Path("data/mock_db.json")
    deals = []
    if db_path.exists():
        try:
            db_data = json.loads(db_path.read_text(encoding="utf-8"))
            deals = [
                deal for deal in db_data.get("deals", [])
                if deal.get("merchant_id") == merchant_id
            ]
        except Exception as e:
            logger.warning(f"Could not read mock DB for static template: {e}")

    page_title = f"{merchant_name} Coupons - Static Fallback"
    cards = []
    for deal in deals:
        code = escape(str(deal.get("code", "")))
        discount = escape(str(deal.get("discount", "")))
        description = escape(str(deal.get("description", "")))
        expiry = escape(str(deal.get("expiry", "")))
        cards.append(
            f"""
            <section class="gc-box" data-gcpn-type="coupon">
              <p class="title">{discount}</p>
              <div class="gcbr"><span>{discount}</span></div>
              <div class="cpn-det-v2">{description} Valid Till: {expiry}</div>
              <button data-code="{code}" data-inner-text="{code}" data-type="cpn-code-text">{code}</button>
            </section>
            """
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{escape(page_title)}</title>
</head>
<body>
  <main data-template-source="mock_db" data-merchant-id="{escape(merchant_id)}">
    <h1>{escape(merchant_name)} Coupons</h1>
    {''.join(cards)}
  </main>
</body>
</html>"""

    saved_path = None
    try:
        scraped_dir = Path("data/scraped")
        scraped_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_path = str(scraped_dir / f"{merchant_id}_static_template_{timestamp}.html")
        Path(saved_path).write_text(html, encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not save static template HTML: {e}")

    return {
        "html": html,
        "page_title": page_title,
        "status_code": 200,
        "saved_path": saved_path,
        "template_source": "mock_db",
        "error_type": None,
    }


registry = get_registry()
registry.register(
    name="static_template",
    description="Generate static fallback HTML from mock DB when live scrapers fail",
    timeout_seconds=5,
    cost_annotation="FREE",
    schema=StaticTemplateInput,
)(static_template)
