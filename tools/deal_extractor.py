"""
Deal extraction from HTML using LLM.

Uses LLMRouter to call Gemini Flash for extraction of coupon codes
and deals from raw HTML. Parses structured JSON response and returns
DealRecords with confidence scores.
"""

import json
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from agent.state import DealRecord
from llm.router import LLMRouter, TaskType
from tools.registry import get_registry

logger = logging.getLogger(__name__)


class DealExtractorInput(BaseModel):
    """Input schema for extract_deals tool."""
    html: str = Field(..., description="Raw HTML content to extract deals from")
    merchant_name: str = Field(..., description="Name of the merchant")
    merchant_id: str = Field(..., description="ID of the merchant")


class DealExtractorOutput(BaseModel):
    """Output schema for extract_deals tool."""
    deals: list[DealRecord] = Field(default_factory=list)
    extraction_confidence: float = Field(default=0.0)
    deals_found_count: int = Field(default=0)
    llm_provider_used: str = Field(default="")
    tokens_used: int = Field(default=0)


def extract_deals(
    html: str,
    merchant_name: str,
    merchant_id: str,
) -> dict:
    """
    Extract deals from HTML using LLM.
    
    Args:
        html: Raw HTML content
        merchant_name: Name of merchant (e.g., "Amazon")
        merchant_id: ID of merchant (e.g., "amazon")
    
    Returns:
        Dictionary with deals list, confidence, tokens_used, provider_used
    """
    logger.info(f"Extracting deals from {merchant_name} ({len(html)} chars)")
    
    if not html or len(html.strip()) == 0:
        logger.warning(f"Empty HTML for {merchant_name}")
        return {
            "deals": [],
            "extraction_confidence": 0.0,
            "deals_found_count": 0,
            "llm_provider_used": "N/A",
            "tokens_used": 0,
            "cost_usd": 0.0,
        }
    
    # Prepare prompt from relevant deal/coupon sections to avoid losing useful data
    soup = BeautifulSoup(html, "lxml")
    relevant_tags = soup.find_all(class_=lambda c: c and any(
        keyword in c.lower()
        for keyword in ["coupon", "deal", "offer", "code", "discount"]
    ))
    clipboard_tags = soup.find_all(attrs={"data-clipboard-text": True})
    clipboard_codes = [
        tag.get("data-clipboard-text")
        for tag in clipboard_tags
        if tag.get("data-clipboard-text")
    ]
    attribute_codes = _extract_attribute_codes(soup)
    script_codes = _extract_script_coupon_codes(html)
    found_codes = _dedupe_codes(clipboard_codes + attribute_codes + script_codes)
    relevant_html = "\n".join(str(tag) for tag in (clipboard_tags + relevant_tags)[:30])
    html_truncated = relevant_html[:6000] if relevant_html else html[:6000]
    
    prompt = f"""You are a deal extraction specialist. Extract ALL coupon codes and deals from this HTML.
Look inside div tags, span tags, button text, data attributes, input values,
JavaScript variables, and any text that looks like a promo code.

Pay special attention to these locations because GrabOn often stores codes there:
- data-clipboard-text attributes
- data-code attributes
- data-coupon attributes
- button text that looks like a promo code
- any uppercase alphanumeric string 5-15 characters long

Merchant: {merchant_name}
Found these clipboard/attribute/script codes: {found_codes}

HTML: {html_truncated}

Return ONLY valid JSON in this exact format:
{{
  "deals": [
    {{
      "code": "COUPON123",
      "discount": "20% off",
      "description": "20% off on orders above Rs 499",
      "expiry": "2025-12-31",
      "min_order": 499,
      "conditions": "New users only"
    }}
  ],
  "extraction_confidence": 0.95,
  "deals_found_count": 3
}}

If no deals found, return: {{"deals": [], "extraction_confidence": 0.0, "deals_found_count": 0}}
Do NOT hallucinate coupon codes. Only extract what is explicitly visible in the HTML.
Return ONLY the JSON, no other text."""
    
    try:
        # Call LLM with DEAL_EXTRACTION task
        router = LLMRouter()
        response_text, tokens_used, cost_usd, provider_used = router.call_with_tracking(
            task_type=TaskType.DEAL_EXTRACTION.value,
            prompt=prompt,
            max_tokens=2048,
        )
        
        logger.info(f"LLM response received: {len(response_text)} chars, provider={provider_used}")
        
        # Parse JSON response
        try:
            # Try to extract JSON from response (in case LLM adds extra text)
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                logger.error(f"No JSON found in LLM response for {merchant_name}")
                return {
                    "deals": [],
                    "extraction_confidence": 0.0,
                    "deals_found_count": 0,
                    "llm_provider_used": provider_used,
                    "tokens_used": tokens_used,
                    "cost_usd": cost_usd,
                }
            
            json_str = response_text[json_start:json_end]
            parsed = json.loads(json_str)
            
            # Validate response structure
            if not isinstance(parsed, dict):
                logger.error(f"LLM response is not a dict for {merchant_name}")
                return {
                    "deals": [],
                    "extraction_confidence": 0.0,
                    "deals_found_count": 0,
                    "llm_provider_used": provider_used,
                    "tokens_used": tokens_used,
                    "cost_usd": cost_usd,
                }
            
            # Extract fields
            deals_list = parsed.get("deals", [])
            confidence = float(parsed.get("extraction_confidence", 0.0))
            found_count = int(parsed.get("deals_found_count", 0))
            
            # Convert to DealRecord objects
            deals = []
            for deal_dict in deals_list:
                try:
                    code = _clean_optional_str(deal_dict.get("code"))
                    if not code:
                        logger.warning(f"Skipping extracted deal without coupon code: {deal_dict}")
                        continue

                    deal = DealRecord(
                        code=code,
                        discount=_clean_optional_str(deal_dict.get("discount")),
                        description=_clean_optional_str(deal_dict.get("description")),
                        expiry=_clean_optional_str(deal_dict.get("expiry")) or "2026-12-31",
                        min_order=_parse_min_order(deal_dict.get("min_order")),
                        source="LIVE",
                        conditions=_clean_optional_str(deal_dict.get("conditions")) or None,
                    )
                    deals.append(deal)
                except Exception as e:
                    logger.warning(f"Could not parse deal: {e}")
                    continue

            existing_codes = {deal.code for deal in deals}
            for code in found_codes:
                if code in existing_codes:
                    continue
                deals.append(DealRecord(
                    code=code,
                    discount="",
                    description=f"Coupon code found in {merchant_name} page attributes/scripts",
                    expiry="2026-12-31",
                    min_order=0,
                    source="LIVE",
                ))
                existing_codes.add(code)
            
            logger.info(f"Extracted {len(deals)} deals from {merchant_name} (confidence={confidence})")
            
            return {
                "deals": deals,
                "extraction_confidence": confidence,
                "deals_found_count": found_count,
                "llm_provider_used": provider_used,
                "tokens_used": tokens_used,
                "cost_usd": cost_usd,
            }
        
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error for {merchant_name}: {e}")
            logger.debug(f"Response was: {response_text[:500]}")
            return {
                "deals": [],
                "extraction_confidence": 0.0,
                "deals_found_count": 0,
                "llm_provider_used": provider_used,
                "tokens_used": tokens_used,
                "cost_usd": cost_usd,
            }
    
    except Exception as e:
        logger.error(f"Deal extraction failed for {merchant_name}: {e}")
        return {
            "deals": [],
            "extraction_confidence": 0.0,
            "deals_found_count": 0,
            "llm_provider_used": "ERROR",
            "tokens_used": 0,
            "cost_usd": 0.0,
        }


def _extract_attribute_codes(soup: BeautifulSoup) -> list[str]:
    """Extract coupon-like values from common code-bearing attributes."""
    codes = []
    for attr_name in ["data-code", "data-coupon", "data-coupon-code", "data-clipboard-text", "value"]:
        for tag in soup.find_all(attrs={attr_name: True}):
            value = tag.get(attr_name)
            if value:
                codes.extend(_find_coupon_like_tokens(str(value)))
    return codes


def _extract_script_coupon_codes(html: str) -> list[str]:
    """Extract coupon codes embedded in GrabOn JavaScript payloads."""
    codes = re.findall(r'"CouponCode"\s*:\s*"([^"]+)"', html)
    codes.extend(re.findall(r"'CouponCode'\s*:\s*'([^']+)'", html))
    codes.extend(
        f"OFFER{coupon_id}"
        for coupon_id in re.findall(r'"CouponID"\s*:\s*(\d+).*?"CouponCode"\s*:\s*""', html)
    )
    return [code for code in codes if code]


def _find_coupon_like_tokens(text: str) -> list[str]:
    """Find uppercase alphanumeric strings that look like coupon codes."""
    return re.findall(r"\b[A-Z0-9]{5,15}\b", text)


def _dedupe_codes(codes: list[str]) -> list[str]:
    """Clean and de-duplicate coupon code candidates while preserving order."""
    seen = set()
    deduped = []
    ignored_codes = {"ACTIVATE", "ACTIVATED", "APPLIED", "COUPON", "COUPONS", "OFFER", "OFFERS"}
    for code in codes:
        clean_code = _clean_optional_str(code).upper()
        if not clean_code or clean_code in seen or clean_code in ignored_codes:
            continue
        if not re.fullmatch(r"[A-Z0-9]{5,15}", clean_code):
            continue
        seen.add(clean_code)
        deduped.append(clean_code)
    return deduped


def _clean_optional_str(value) -> str:
    """Convert nullable LLM fields to clean strings."""
    if value is None:
        return ""
    return str(value).strip()


def _parse_min_order(value) -> int:
    """Parse nullable or free-text minimum order values from LLM output."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else 0


# Register the tool
registry = get_registry()
registry.register(
    name="extract_deals",
    description="Extract deals and coupon codes from HTML using LLM",
    timeout_seconds=30,
    cost_annotation="MEDIUM",
    schema=DealExtractorInput,
)(extract_deals)
