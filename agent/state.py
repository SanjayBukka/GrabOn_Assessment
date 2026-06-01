"""Agent state management and Pydantic models."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class DealStatus(str, Enum):
    """Classification status for a deal."""
    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"
    UPDATED = "UPDATED"
    EXTRA = "EXTRA"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


class DealRecord(BaseModel):
    """Represents a single deal/coupon code."""
    code: str
    discount: str
    description: str = ""
    expiry: str
    min_order: int = 0
    source: str = Field(default="LIVE", description="DB or LIVE")
    conditions: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "code": "AMZNEW10",
                "discount": "10%",
                "description": "10% off on electronics",
                "expiry": "2025-12-31",
                "min_order": 500,
                "source": "DB"
            }
        }


class ClassifiedDeal(BaseModel):
    """A deal with its classification status."""
    code: str
    discount: str
    description: str = ""
    expiry: str
    min_order: int = 0
    source: str
    status: DealStatus
    db_discount: Optional[str] = None
    live_discount: Optional[str] = None
    expired: bool = False


class Phase(str, Enum):
    """Explicit phases of the POAD loop."""
    PLAN = "PLAN"
    ACT = "ACT"
    OBSERVE = "OBSERVE"
    DECIDE = "DECIDE"


class AgentIteration(BaseModel):
    """Single step in the agent loop."""
    step_number: int
    phase: Phase
    action: str
    tool_called: Optional[str] = None
    observation: str = ""
    decision: str = ""
    tokens_consumed: int = 0
    wall_clock_time: float = 0.0
    llm_provider: Optional[str] = None
    cost_usd: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class MerchantResult(BaseModel):
    """Results for a single merchant audit."""
    merchant_id: str
    name: str
    url: str
    db_deals: list[DealRecord] = Field(default_factory=list)
    live_deals: list[DealRecord] = Field(default_factory=list)
    classified_deals: list[ClassifiedDeal] = Field(default_factory=list)
    status: str = "pending"  # completed, failed, error, skipped
    error_message: Optional[str] = None
    tool_calls_used: int = 0
    time_taken: float = 0.0
    health_score: float = 0.0
    fallback_used: bool = False
    recovery_events: list[dict] = Field(default_factory=list)


class AgentState(BaseModel):
    """Overall state of the agent session."""
    session_id: str
    start_time: datetime = Field(default_factory=datetime.utcnow)
    merchants_total: int = 0
    merchants_completed: int = 0
    merchants_failed: int = 0
    current_merchant: Optional[str] = None
    iterations: list[AgentIteration] = Field(default_factory=list)
    merchant_results: list[MerchantResult] = Field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_tool_calls: int = 0
    consecutive_failures: int = 0
    budget_exceeded: bool = False
    final_report: Optional[dict[str, Any]] = None
    wall_clock_start: float = 0.0
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class BudgetStatus(BaseModel):
    """Budget check result."""
    ok: bool
    reason: Optional[str] = None
    report: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Result from a tool execution."""
    success: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    error_type: Optional[str] = None  # TRANSIENT, PERMANENT, RATE_LIMIT, NOT_FOUND, TIMEOUT
    latency_ms: float = 0.0
    tool_name: str = ""


class ScraperOutput(BaseModel):
    """Output from scraper tools."""
    html: Optional[str] = None
    page_title: Optional[str] = None
    status_code: int = 0
    saved_path: Optional[str] = None
    error_type: Optional[str] = None


class ExtractorOutput(BaseModel):
    """Output from deal extraction."""
    deals: list[DealRecord] = Field(default_factory=list)
    extraction_confidence: float = 0.0
    deals_found_count: int = 0
    llm_provider_used: str = ""
    tokens_used: int = 0


class ClassifierOutput(BaseModel):
    """Output from deal classifier."""
    classified_deals: list[ClassifiedDeal] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    merchant_health_score: float = 0.0


class DBLookupOutput(BaseModel):
    """Output from database lookup."""
    deals: list[DealRecord] = Field(default_factory=list)
    merchant_found: bool = False
    deal_count: int = 0
