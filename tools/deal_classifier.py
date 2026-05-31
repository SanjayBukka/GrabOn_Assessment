"""
Deal classifier comparing live vs database deals.

Classifies each deal as FRESH, STALE, MISSING, UPDATED, or EXTRA
by comparing codes, discounts, and expiry dates.
Uses simple code-based logic (no LLM for most cases).
"""

import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from agent.state import DealStatus, DealRecord, ClassifiedDeal
from tools.registry import get_registry

logger = logging.getLogger(__name__)


class DealClassifierInput(BaseModel):
    """Input schema for classify_deals tool."""
    merchant_id: str = Field(..., description="Merchant ID")
    db_deals: list[DealRecord] = Field(default_factory=list, description="Deals from database")
    live_deals: list[DealRecord] = Field(default_factory=list, description="Deals from live page")


class DealClassifierOutput(BaseModel):
    """Output schema for classify_deals tool."""
    classified_deals: list[ClassifiedDeal] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    merchant_health_score: float = Field(default=0.0)


def classify_deals(
    merchant_id: str,
    db_deals: list[DealRecord],
    live_deals: list[DealRecord],
) -> dict:
    """
    Classify deals by comparing database vs live deals.
    
    Args:
        merchant_id: Merchant ID
        db_deals: Deals from internal database
        live_deals: Deals scraped from live page
    
    Returns:
        Dictionary with classified_deals list, summary counts, health_score
    """
    logger.info(
        f"Classifying deals for {merchant_id}: "
        f"{len(db_deals)} DB deals, {len(live_deals)} live deals"
    )
    
    classified_deals = []
    summary = {
        "fresh": 0,
        "stale": 0,
        "missing": 0,
        "updated": 0,
        "extra": 0,
        "unknown": 0,
        "error": 0,
    }
    
    # Create lookup maps by code
    db_map = {deal.code: deal for deal in db_deals}
    live_map = {deal.code: deal for deal in live_deals}
    
    # Classify each DB deal
    for db_deal in db_deals:
        code = db_deal.code
        
        if code in live_map:
            live_deal = live_map[code]
            
            # Deal exists in both DB and live
            is_expired = _is_expired(live_deal.expiry)
            discount_matches = db_deal.discount == live_deal.discount
            
            if discount_matches and not is_expired:
                # FRESH: matches and not expired
                status = DealStatus.FRESH
                summary["fresh"] += 1
            elif discount_matches and is_expired:
                # STALE: matches but expired
                status = DealStatus.STALE
                summary["stale"] += 1
            elif not discount_matches and not is_expired:
                # UPDATED: active deal exists on live page with changed discount
                status = DealStatus.UPDATED
                summary["updated"] += 1
            else:
                # STALE: expired and discount changed, or another expiry-related issue
                status = DealStatus.STALE
                summary["stale"] += 1
            
            classified = ClassifiedDeal(
                code=code,
                discount=db_deal.discount,
                description=db_deal.description,
                expiry=db_deal.expiry,
                min_order=db_deal.min_order,
                source="DB",
                status=status,
                db_discount=db_deal.discount,
                live_discount=live_deal.discount,
                expired=is_expired,
            )
            classified_deals.append(classified)
        
        else:
            # MISSING: in DB but not on live page
            status = DealStatus.MISSING
            summary["missing"] += 1
            
            classified = ClassifiedDeal(
                code=code,
                discount=db_deal.discount,
                description=db_deal.description,
                expiry=db_deal.expiry,
                min_order=db_deal.min_order,
                source="DB",
                status=status,
                db_discount=db_deal.discount,
                live_discount=None,
                expired=_is_expired(db_deal.expiry),
            )
            classified_deals.append(classified)
    
    # Find EXTRA deals (on live but not in DB)
    for live_deal in live_deals:
        code = live_deal.code
        
        if code not in db_map:
            # EXTRA: on live page but not in DB
            status = DealStatus.EXTRA
            summary["extra"] += 1
            
            classified = ClassifiedDeal(
                code=code,
                discount=live_deal.discount,
                description=live_deal.description,
                expiry=live_deal.expiry,
                min_order=live_deal.min_order,
                source="LIVE",
                status=status,
                db_discount=None,
                live_discount=live_deal.discount,
                expired=_is_expired(live_deal.expiry),
            )
            classified_deals.append(classified)
    
    # Calculate health score (percentage of FRESH deals)
    total_db_deals = len(db_deals)
    fresh_count = summary["fresh"]
    health_score = (
        (fresh_count / total_db_deals * 100)
        if total_db_deals > 0
        else 0.0
    )
    
    logger.info(
        f"Classification complete: {summary['fresh']} fresh, "
        f"{summary['stale']} stale, {summary['missing']} missing, "
        f"{summary['extra']} extra (health={health_score:.1f}%)"
    )
    
    return {
        "classified_deals": classified_deals,
        "summary": summary,
        "merchant_health_score": round(health_score, 2),
    }


def _is_expired(expiry_date_str: str) -> bool:
    """
    Check if a deal is expired based on expiry date string.
    
    Args:
        expiry_date_str: Date string in format "YYYY-MM-DD"
    
    Returns:
        True if expired, False if still valid
    """
    try:
        if not expiry_date_str:
            return False
        
        expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        
        return expiry_date < today
    
    except (ValueError, TypeError):
        logger.warning(f"Could not parse expiry date: {expiry_date_str}")
        return False


# Register the tool
registry = get_registry()
registry.register(
    name="classify_deals",
    description="Classify deals by comparing database vs live deals",
    timeout_seconds=10,
    cost_annotation="FREE",
    schema=DealClassifierInput,
)(classify_deals)
