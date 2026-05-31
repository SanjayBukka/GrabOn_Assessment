"""
Mock database lookup for GrabOn's internal deal database.

Queries data/mock_db.json to fetch deals for a given merchant.
Returns list of DealRecords with source="DB".
"""

import json
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from agent.state import DealRecord
from tools.registry import get_registry

logger = logging.getLogger(__name__)


class DBLookupInput(BaseModel):
    """Input schema for db_lookup tool."""
    merchant_id: str = Field(..., description="Merchant ID to look up in database")


class DBLookupOutput(BaseModel):
    """Output schema for db_lookup tool."""
    deals: list[DealRecord] = Field(default_factory=list)
    merchant_found: bool = Field(default=False)
    deal_count: int = Field(default=0)


def db_lookup(merchant_id: str) -> dict:
    """
    Query mock database for a merchant's deals.
    
    Args:
        merchant_id: ID of merchant to look up (e.g., "amazon")
    
    Returns:
        Dictionary with deals list, merchant_found flag, deal_count
    """
    logger.info(f"Looking up deals for merchant: {merchant_id}")
    
    try:
        # Load mock database
        db_path = Path("data/mock_db.json")
        
        if not db_path.exists():
            logger.error(f"Database file not found: {db_path}")
            return {
                "deals": [],
                "merchant_found": False,
                "deal_count": 0,
            }
        
        with open(db_path, "r", encoding="utf-8") as f:
            db_data = json.load(f)
        
        # Get all deals
        all_deals = db_data.get("deals", [])
        
        # Filter by merchant_id
        merchant_deals = [
            deal for deal in all_deals
            if deal.get("merchant_id") == merchant_id
        ]
        
        # Convert to DealRecord objects
        deals = []
        for deal_dict in merchant_deals:
            try:
                deal = DealRecord(
                    code=deal_dict.get("code", ""),
                    discount=deal_dict.get("discount", ""),
                    description=deal_dict.get("description", ""),
                    expiry=deal_dict.get("expiry", ""),
                    min_order=deal_dict.get("min_order", 0),
                    source="DB",
                    conditions=None,
                )
                deals.append(deal)
            except Exception as e:
                logger.warning(f"Could not parse deal: {e}")
                continue
        
        merchant_found = len(deals) > 0
        
        logger.info(
            f"Found {len(deals)} deal(s) for {merchant_id} "
            f"(merchant_found={merchant_found})"
        )
        
        return {
            "deals": deals,
            "merchant_found": merchant_found,
            "deal_count": len(deals),
        }
    
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding database JSON: {e}")
        return {
            "deals": [],
            "merchant_found": False,
            "deal_count": 0,
        }
    
    except Exception as e:
        logger.error(f"Database lookup failed for {merchant_id}: {e}")
        return {
            "deals": [],
            "merchant_found": False,
            "deal_count": 0,
        }


# Register the tool
registry = get_registry()
registry.register(
    name="db_lookup",
    description="Query GrabOn's internal database for a merchant's deals",
    timeout_seconds=5,
    cost_annotation="FREE",
    schema=DBLookupInput,
)(db_lookup)
