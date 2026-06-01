"""
Unreliable coupon verifier tool (intentionally fails 30% of the time).
Simulates verification of coupon codes against merchant systems.
Designed to fail randomly to test agent's retry and recovery logic.
30% failure rate is intentional and documented.
"""

import logging
import random
from typing import Optional

from pydantic import BaseModel, Field

from tools.registry import get_registry

logger = logging.getLogger(__name__)


class VerifyCouponInput(BaseModel):
    """Input schema for verify_coupon tool."""
    merchant_id: str = Field(..., description="Merchant ID")
    coupon_code: str = Field(..., description="Coupon code to verify")


class VerifyCouponOutput(BaseModel):
    """Output schema for verify_coupon tool."""
    is_active: Optional[bool] = Field(default=None)
    verified_discount: Optional[str] = Field(default=None)
    verified_expiry: Optional[str] = Field(default=None)
    verification_source: str = Field(default="mock_verifier_v1")


def verify_coupon(
    merchant_id: str,
    coupon_code: str,
) -> dict:
    """
    Verify if a coupon code is active (intentionally unreliable).
    
    This tool fails 30% of the time to simulate unreliable external systems
    and test the agent's retry and recovery logic.
    
    Args:
        merchant_id: Merchant ID
        coupon_code: Coupon code to verify
    
    Returns:
        Dictionary with is_active, verified_discount, verified_expiry, verification_source
    
    Raises:
        Exception: Randomly (30% of time) to test retry logic
    """
    logger.info(f"Verifying coupon {coupon_code} for {merchant_id}")
    
    # Simulate failure 30% of the time
    if random.random() < 0.30:
        logger.warning(f"Verification failed for {coupon_code} (intentional)")
        
        # Randomly pick error type
        error_choice = random.choice([
            "TimeoutError",
            "ConnectionError",
            "HTTPError503",
        ])
        
        if error_choice == "TimeoutError":
            raise TimeoutError(f"Verification timeout for {coupon_code}")
        elif error_choice == "ConnectionError":
            raise ConnectionError(f"Connection error verifying {coupon_code}")
        else:  # HTTPError503
            raise Exception(f"HTTP 503 Service Unavailable verifying {coupon_code}")
    
    # Success: generate mock verification
    is_active = random.random() < 0.80  # 80% chance coupon is active
    
    # Mock verified values
    verified_discount = "10-25%" if is_active else None
    verified_expiry = "2025-12-31" if is_active else None
    
    logger.info(
        f"Verification succeeded for {coupon_code}: "
        f"is_active={is_active}, discount={verified_discount}"
    )
    
    return {
        "is_active": is_active,
        "verified_discount": verified_discount,
        "verified_expiry": verified_expiry,
        "verification_source": "mock_verifier_v1",
    }


# Register the tool
registry = get_registry()
registry.register(
    name="verify_coupon",
    description="Verify if a coupon code is active (INTENTIONALLY UNRELIABLE - 30% failure rate)",
    timeout_seconds=15,
    cost_annotation="LOW",
    schema=VerifyCouponInput,
)(verify_coupon)
