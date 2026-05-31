"""
Agent planner that creates step-by-step execution plans using LLM.

Uses LLMRouter to call Groq for planning based on merchant info,
available tools, and current budget status.
Supports re-planning when tools fail.
"""

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from llm.router import LLMRouter, TaskType
from tools.registry import get_registry

logger = logging.getLogger(__name__)


class PlanStep(BaseModel):
    """A single step in the execution plan."""
    step: int
    tool: str
    reason: str


class Plan(BaseModel):
    """Complete execution plan for a merchant."""
    steps: list[PlanStep] = Field(default_factory=list)
    fallback_if_scrape_fails: str = Field(default="google_cache")
    estimated_tool_calls: int = Field(default=4)


class AgentPlanner:
    """
    LLM-based planner for merchant audit strategy.
    
    Creates detailed plans for each merchant with tool sequence,
    fallback strategies, and handles re-planning on failures.
    """
    
    def __init__(self):
        """Initialize planner with LLM router."""
        self.router = LLMRouter()
    
    async def create_plan(
        self,
        merchant_id: str,
        merchant_name: str,
        merchant_url: str,
        tokens_used: int,
        max_tokens: int,
        tool_calls_used: int,
        max_tool_calls: int,
    ) -> Plan:
        """
        Create execution plan for a merchant.
        
        Args:
            merchant_id: Merchant ID
            merchant_name: Human-readable merchant name
            merchant_url: URL to audit
            tokens_used: Tokens consumed so far
            max_tokens: Token limit
            tool_calls_used: Tool calls made so far
            max_tool_calls: Tool call limit
        
        Returns:
            Plan object with steps and strategy
        """
        logger.info(f"Creating plan for {merchant_name}")
        
        # Get available tools
        registry = get_registry()
        tools_list = registry.list_tools()
        tools_str = ", ".join([f"{t.name} - {t.description}" for t in tools_list])
        
        # Build prompt
        prompt = f"""You are an agent planner for GrabOn's deal audit system.

Merchant: {merchant_name} (ID: {merchant_id})
URL: {merchant_url}

Available tools:
{tools_str}

Current budget used:
- Tokens: {tokens_used}/{max_tokens} ({self._percent(tokens_used, max_tokens)}%)
- Tool calls: {tool_calls_used}/{max_tool_calls} ({self._percent(tool_calls_used, max_tool_calls)}%)

Create a step-by-step plan to:
1. Scrape this merchant's deal page
2. Extract deals
3. Compare with our database
4. Classify each deal

Be efficient - minimize tool calls given remaining budget.

Return ONLY valid JSON in this exact format:
{{
  "steps": [
    {{"step": 1, "tool": "scrape_html", "reason": "Start with direct HTTP scrape"}},
    {{"step": 2, "tool": "extract_deals", "reason": "Parse HTML for coupon codes"}},
    {{"step": 3, "tool": "db_lookup", "reason": "Get internal DB records"}},
    {{"step": 4, "tool": "classify_deals", "reason": "Compare and classify"}}
  ],
  "fallback_if_scrape_fails": "google_cache",
  "estimated_tool_calls": 4
}}

Return ONLY the JSON, no other text."""
        
        try:
            response_text, tokens_used_call, cost_usd, provider = self.router.call_with_tracking(
                task_type=TaskType.PLANNING.value,
                prompt=prompt,
                max_tokens=1024,
            )
            
            logger.info(f"Plan response received from {provider}")
            
            # Parse JSON response
            plan = self._parse_plan_response(response_text)
            
            logger.info(
                f"Plan created for {merchant_name}: "
                f"{len(plan.steps)} steps, "
                f"fallback={plan.fallback_if_scrape_fails}"
            )
            
            return plan
        
        except Exception as e:
            logger.error(f"Planning failed for {merchant_name}: {e}")
            # Return default plan on failure
            return self._default_plan()
    
    async def replan(
        self,
        merchant_id: str,
        merchant_name: str,
        merchant_url: str,
        failed_tool: str,
        error_type: str,
        tokens_used: int,
        max_tokens: int,
        tool_calls_used: int,
        max_tool_calls: int,
    ) -> Plan:
        """
        Create alternative plan when a tool fails.
        
        Args:
            merchant_id: Merchant ID
            merchant_name: Merchant name
            merchant_url: URL
            failed_tool: Tool that failed
            error_type: Type of error (TRANSIENT, PERMANENT, RATE_LIMIT, etc.)
            tokens_used: Tokens consumed
            max_tokens: Token limit
            tool_calls_used: Tool calls used
            max_tool_calls: Tool call limit
        
        Returns:
            Alternative Plan
        """
        logger.info(f"Re-planning for {merchant_name} after {failed_tool} failure ({error_type})")
        
        # Get available tools
        registry = get_registry()
        tools_list = registry.list_tools()
        tools_str = ", ".join([f"{t.name} - {t.description}" for t in tools_list])
        
        # Build re-plan prompt
        error_strategy = self._get_error_strategy(error_type)
        
        prompt = f"""You are an agent planner for GrabOn's deal audit system.

REPLAN REQUIRED:
Merchant: {merchant_name} (ID: {merchant_id})
URL: {merchant_url}
Failed tool: {failed_tool}
Error type: {error_type}
Recovery strategy: {error_strategy}

Available tools:
{tools_str}

Current budget used:
- Tokens: {tokens_used}/{max_tokens}
- Tool calls: {tool_calls_used}/{max_tool_calls}

Create an alternative plan that:
1. Works around the failure of {failed_tool}
2. Uses fallback tools if available
3. Achieves the audit goal

Return ONLY valid JSON in this exact format:
{{
  "steps": [
    {{"step": 1, "tool": "google_cache", "reason": "Fallback: fetch from cache"}},
    {{"step": 2, "tool": "extract_deals", "reason": "Extract from cached HTML"}},
    {{"step": 3, "tool": "db_lookup", "reason": "Get DB records"}},
    {{"step": 4, "tool": "classify_deals", "reason": "Classify deals"}}
  ],
  "fallback_if_scrape_fails": "scrape_js",
  "estimated_tool_calls": 4
}}

Return ONLY the JSON, no other text."""
        
        try:
            response_text, tokens_used_call, cost_usd, provider = self.router.call_with_tracking(
                task_type=TaskType.PLANNING.value,
                prompt=prompt,
                max_tokens=1024,
            )
            
            plan = self._parse_plan_response(response_text)
            
            logger.info(f"Re-plan created for {merchant_name}: {len(plan.steps)} steps")
            
            return plan
        
        except Exception as e:
            logger.error(f"Re-planning failed for {merchant_name}: {e}")
            return self._default_plan()
    
    def _parse_plan_response(self, response_text: str) -> Plan:
        """
        Parse LLM response into Plan object.
        
        Args:
            response_text: LLM response text
        
        Returns:
            Plan object
        
        Raises:
            ValueError: If response cannot be parsed
        """
        try:
            # Extract JSON from response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                raise ValueError("No JSON found in response")
            
            json_str = response_text[json_start:json_end]
            parsed = json.loads(json_str)
            
            # Parse steps
            steps = []
            for step_dict in parsed.get("steps", []):
                step = PlanStep(
                    step=step_dict.get("step", 0),
                    tool=step_dict.get("tool", ""),
                    reason=step_dict.get("reason", ""),
                )
                steps.append(step)
            
            plan = Plan(
                steps=steps,
                fallback_if_scrape_fails=parsed.get("fallback_if_scrape_fails", "google_cache"),
                estimated_tool_calls=parsed.get("estimated_tool_calls", 4),
            )
            
            return plan
        
        except Exception as e:
            logger.error(f"Failed to parse plan response: {e}")
            raise
    
    def _default_plan(self) -> Plan:
        """Return default plan when LLM planning fails."""
        return Plan(
            steps=[
                PlanStep(step=1, tool="scrape_html", reason="Direct HTTP scrape"),
                PlanStep(step=2, tool="extract_deals", reason="Extract deals from HTML"),
                PlanStep(step=3, tool="db_lookup", reason="Get DB records"),
                PlanStep(step=4, tool="classify_deals", reason="Classify and compare"),
            ],
            fallback_if_scrape_fails="google_cache",
            estimated_tool_calls=4,
        )
    
    def _get_error_strategy(self, error_type: str) -> str:
        """
        Get recovery strategy for error type.
        
        Args:
            error_type: Type of error
        
        Returns:
            Strategy description
        """
        strategies = {
            "TRANSIENT": "Retry with exponential backoff or use alternative tool",
            "RATE_LIMIT": "Use cache or wait before retrying",
            "NOT_FOUND": "Mark merchant as unavailable",
            "TIMEOUT": "Switch to slower but more reliable tool (e.g., Playwright)",
            "PERMANENT": "Use fallback tool or graceful degradation",
        }
        return strategies.get(error_type, "Use fallback tool")
    
    def _percent(self, used: int, total: int) -> str:
        """Format percentage for display."""
        if total == 0:
            return "0"
        return f"{int(used / total * 100)}"
