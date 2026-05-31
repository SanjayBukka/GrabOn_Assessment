"""
Deal extraction from HTML using LLM.

Uses LLMRouter to call Gemini Flash for extraction of coupon codes
and deals from raw HTML. Parses structured JSON response and returns
DealRecords with confidence scores.
"""

import json
import logging
from typing import Optional

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
        }
    
    # Prepare prompt
    # Truncate HTML to 8000 chars to avoid token limits
    html_truncated = html[:8000]
    
    prompt = f"""You are a deal extraction specialist. Extract all coupon codes and deals from this HTML.

Merchant: {merchant_name}
HTML Content: {html_truncated}

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
                }
            
            # Extract fields
            deals_list = parsed.get("deals", [])
            confidence = float(parsed.get("extraction_confidence", 0.0))
            found_count = int(parsed.get("deals_found_count", 0))
            
            # Convert to DealRecord objects
            deals = []
            for deal_dict in deals_list:
                try:
                    deal = DealRecord(
                        code=deal_dict.get("code", ""),
                        discount=deal_dict.get("discount", ""),
                        description=deal_dict.get("description", ""),
                        expiry=deal_dict.get("expiry", ""),
                        min_order=deal_dict.get("min_order", 0),
                        source="LIVE",
                        conditions=deal_dict.get("conditions"),
                    )
                    deals.append(deal)
                except Exception as e:
                    logger.warning(f"Could not parse deal: {e}")
                    continue
            
            logger.info(f"Extracted {len(deals)} deals from {merchant_name} (confidence={confidence})")
            
            return {
                "deals": deals,
                "extraction_confidence": confidence,
                "deals_found_count": found_count,
                "llm_provider_used": provider_used,
                "tokens_used": tokens_used,
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
            }
    
    except Exception as e:
        logger.error(f"Deal extraction failed for {merchant_name}: {e}")
        return {
            "deals": [],
            "extraction_confidence": 0.0,
            "deals_found_count": 0,
            "llm_provider_used": "ERROR",
            "tokens_used": 0,
        }


# Register the tool
registry = get_registry()
registry.register(
    name="extract_deals",
    description="Extract deals and coupon codes from HTML using LLM",
    timeout_seconds=30,
    cost_annotation="MEDIUM",
    schema=DealExtractorInput,
)(extract_deals)
