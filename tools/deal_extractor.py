"""Deal extraction from HTML using LLM."""

import json
import logging
import re
from datetime import datetime
from html import unescape
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
    """Extract deals from HTML using LLM."""
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

    structured_deals = _extract_grabon_structured_deals(html)
    if structured_deals:
        logger.info(
            f"Extracted {len(structured_deals)} structured GrabOn deals from {merchant_name}"
        )
        return {
            "deals": structured_deals,
            "extraction_confidence": 1.0,
            "deals_found_count": len(structured_deals),
            "llm_provider_used": "HTML_STRUCTURED",
            "tokens_used": 0,
            "cost_usd": 0.0,
        }
    if _has_grabon_coupon_cards(html):
        logger.info(f"No real coupon codes found in structured GrabOn cards for {merchant_name}")
        return {
            "deals": [],
            "extraction_confidence": 1.0,
            "deals_found_count": 0,
            "llm_provider_used": "HTML_STRUCTURED",
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


def _extract_grabon_structured_deals(html: str) -> list[DealRecord]:
    """Extract live GrabOn coupon cards directly from rendered HTML."""
    soup = BeautifulSoup(html, "lxml")
    deals = []
    seen_codes = set()

    for card in soup.select(".gc-box"):
        if _is_expired_card(card):
            continue

        code = _extract_card_code(card)
        if not code or code in seen_codes:
            continue

        title = _clean_text(card.select_one("p.title"))
        discount = _clean_text(card.select_one(".gcbr > span"))
        details = _clean_text(card.select_one(".cpn-det-v2"))

        deals.append(DealRecord(
            code=code,
            discount=discount,
            description=details or title,
            expiry=_extract_card_expiry(card),
            min_order=_parse_min_order(f"{title} {details}"),
            source="LIVE",
        ))
        seen_codes.add(code)

    return deals


def _has_grabon_coupon_cards(html: str) -> bool:
    """Detect whether this is a rendered GrabOn merchant page with coupon cards."""
    soup = BeautifulSoup(html, "lxml")
    return bool(soup.select(".gc-box"))


def _is_expired_card(card) -> bool:
    """Return true for expired coupon cards."""
    card_type = (card.get("data-gcpn-type") or "").lower()
    class_names = " ".join(card.get("class", [])).lower()
    return "expired" in card_type or "expired" in class_names


def _extract_card_code(card) -> str:
    """Extract a real coupon code from a GrabOn coupon card."""
    candidates = []

    for attr_name in ["data-code", "data-inner-text"]:
        for tag in card.select(f"[{attr_name}]"):
            value = tag.get(attr_name)
            if value:
                candidates.append(value)

    for tag in card.select("[data-type='cpn-code-text']"):
        candidates.append(tag.get_text(" ", strip=True))

    for candidate in candidates:
        code = _normalize_coupon_code(candidate)
        if code:
            return code

    return ""


def _normalize_coupon_code(value) -> str:
    """Normalize and validate real coupon codes, excluding UI placeholders."""
    code = _clean_optional_str(value).upper()
    if not code:
        return ""
    ignored_codes = {
        "ACTIVATE", "ACTIVATEOFFER", "ACTIVATED", "APPLIED", "CODE", "COUPON",
        "COUPONS", "DEAL", "DEALS", "EXPIRED", "GETCOUPON", "GETDEAL",
        "OFFER", "OFFERS", "SHOWCOUPONCODE",
        "CODEACTIVATED", "CODEAPPLIED", "DEALACTIVATED", "DISCOUNTAPPLIED",
        "ENJOYSAVINGS", "FREESHIPPINGUNLOCKED", "NOCOUPONNEEDED",
        "PRICEREDUCED", "STARTSHOPPING",
    }
    code = re.sub(r"[^A-Z0-9]", "", code)
    if code in ignored_codes:
        return ""
    if code.startswith("OFFER"):
        return ""
    if not re.fullmatch(r"[A-Z0-9]{4,24}", code):
        return ""
    if not any(char.isdigit() for char in code) and len(code) < 5:
        return ""
    return code


def _clean_text(tag) -> str:
    """Convert a BeautifulSoup tag into compact readable text."""
    if not tag:
        return ""
    text = unescape(tag.get_text(" ", strip=True))
    return re.sub(r"\s+", " ", text).strip()


def _extract_card_expiry(card) -> str:
    """Extract an expiry date when present; otherwise use a future audit date."""
    text = card.get_text(" ", strip=True)
    match = re.search(
        r"(?:valid|expires?|ends?)\D{0,20}(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return "2026-12-31"

    day, month, year = match.groups()
    year = f"20{year}" if len(year) == 2 else year
    try:
        return datetime(int(year), int(month), int(day)).strftime("%Y-%m-%d")
    except ValueError:
        return "2026-12-31"


def _extract_script_coupon_codes(html: str) -> list[str]:
    """Extract coupon codes embedded in GrabOn JavaScript payloads."""
    codes = re.findall(r'"CouponCode"\s*:\s*"([^"]+)"', html)
    codes.extend(re.findall(r"'CouponCode'\s*:\s*'([^']+)'", html))
    return [code for code in codes if code]


def _find_coupon_like_tokens(text: str) -> list[str]:
    """Find uppercase alphanumeric strings that look like coupon codes."""
    return re.findall(r"\b[A-Z0-9]{5,15}\b", text)


def _dedupe_codes(codes: list[str]) -> list[str]:
    """Clean and de-duplicate coupon code candidates while preserving order."""
    seen = set()
    deduped = []
    ignored_codes = {"ACTIVATE", "ACTIVATED", "APPLIED", "CODE", "COUPON", "COUPONS", "OFFER", "OFFERS"}
    for code in codes:
        clean_code = _normalize_coupon_code(code)
        if not clean_code or clean_code in seen or clean_code in ignored_codes:
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
