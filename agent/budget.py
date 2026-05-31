"""
Budget enforcement for resource-constrained agent execution.

Tracks token consumption, tool calls, wall clock time, and consecutive failures.
Enforces hard limits and raises BudgetExceededError when exceeded.
"""

import logging
import os
import time
from typing import Optional

from agent.state import BudgetStatus

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """Raised when agent exceeds resource budget."""
    pass


class BudgetEnforcer:
    """
    Enforces resource limits for agent execution.
    
    Tracked limits:
    - MAX_TOKENS_PER_RUN: Total tokens (default 150,000)
    - MAX_WALL_CLOCK_SECONDS: Total execution time (default 900s = 15 min)
    - MAX_TOOL_CALLS: Total tool invocations (default 200)
    - MAX_CONSECUTIVE_FAILURES: Max consecutive failures (default 5)
    """
    
    def __init__(self):
        """Initialize budget enforcer with limits from .env."""
        self.max_tokens = int(os.getenv("MAX_TOKENS_PER_RUN", "150000"))
        self.max_wall_clock_seconds = int(os.getenv("MAX_WALL_CLOCK_SECONDS", "900"))
        self.max_tool_calls = int(os.getenv("MAX_TOOL_CALLS", "200"))
        self.max_consecutive_failures = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "5"))
        
        # Tracking
        self.tokens_used = 0
        self.tokens_by_provider: dict[str, int] = {}
        self.tool_calls_used = 0
        self.tool_calls_by_name: dict[str, int] = {}
        self.consecutive_failures = 0
        self.wall_clock_start = time.time()
        self.is_exceeded = False
        self.exceeded_reason: Optional[str] = None
        
        logger.info(
            f"Budget enforcer initialized: "
            f"tokens={self.max_tokens}, "
            f"time={self.max_wall_clock_seconds}s, "
            f"calls={self.max_tool_calls}, "
            f"failures={self.max_consecutive_failures}"
        )
    
    def record_tokens(self, count: int, provider: str = "unknown") -> None:
        """
        Record token consumption from an LLM call.
        
        Args:
            count: Number of tokens used
            provider: LLM provider name (groq, gemini_flash, etc.)
        """
        provider = self._normalize_provider(provider)
        self.tokens_used += count
        
        if provider not in self.tokens_by_provider:
            self.tokens_by_provider[provider] = 0
        self.tokens_by_provider[provider] += count
        
        logger.debug(f"Recorded {count} tokens from {provider} (total: {self.tokens_used})")

    def _normalize_provider(self, provider: str) -> str:
        """Normalize routed provider labels to cost tracker keys."""
        provider_key = (provider or "unknown").lower().replace("-", "_")
        if provider_key.startswith("groq"):
            return "groq"
        if provider_key.startswith("gemini"):
            return "gemini_flash"
        if provider_key.startswith("openrouter"):
            return "openrouter"
        return provider_key
    
    def record_tool_call(self, tool_name: str, success: bool) -> None:
        """
        Record a tool call and update failure counter.
        
        Args:
            tool_name: Name of tool that was called
            success: True if call succeeded, False if failed
        """
        self.tool_calls_used += 1
        
        if tool_name not in self.tool_calls_by_name:
            self.tool_calls_by_name[tool_name] = 0
        self.tool_calls_by_name[tool_name] += 1
        
        if success:
            self.record_success()
        else:
            self.record_failure()
        
        logger.debug(
            f"Recorded tool call: {tool_name} (success={success}, "
            f"total calls: {self.tool_calls_used})"
        )
    
    def record_failure(self) -> None:
        """Increment consecutive failure counter."""
        self.consecutive_failures += 1
        logger.warning(f"Failure recorded (consecutive: {self.consecutive_failures})")
    
    def record_success(self) -> None:
        """Reset consecutive failure counter on success."""
        if self.consecutive_failures > 0:
            logger.info(f"Success - resetting failure counter from {self.consecutive_failures}")
        self.consecutive_failures = 0
    
    def get_wall_clock_elapsed(self) -> float:
        """Get elapsed wall clock time in seconds."""
        return time.time() - self.wall_clock_start
    
    def check_limits(self, raise_on_exceeded: bool = True) -> BudgetStatus:
        """
        Check if any limits have been exceeded.
        
        Args:
            raise_on_exceeded: If True, raise BudgetExceededError if limit exceeded
        
        Returns:
            BudgetStatus with ok flag and reason
        
        Raises:
            BudgetExceededError: If limit exceeded and raise_on_exceeded=True
        """
        elapsed = self.get_wall_clock_elapsed()
        
        # Check each limit
        if self.tokens_used >= self.max_tokens:
            reason = (
                f"Token limit exceeded: {self.tokens_used}/{self.max_tokens} tokens used"
            )
            self.is_exceeded = True
            self.exceeded_reason = reason
            
            if raise_on_exceeded:
                logger.error(reason)
                raise BudgetExceededError(reason)
            
            return BudgetStatus(
                ok=False,
                reason=reason,
                report=self._build_report(elapsed),
            )
        
        if elapsed >= self.max_wall_clock_seconds:
            reason = (
                f"Wall clock limit exceeded: {elapsed:.1f}/{self.max_wall_clock_seconds}s elapsed"
            )
            self.is_exceeded = True
            self.exceeded_reason = reason
            
            if raise_on_exceeded:
                logger.error(reason)
                raise BudgetExceededError(reason)
            
            return BudgetStatus(
                ok=False,
                reason=reason,
                report=self._build_report(elapsed),
            )
        
        if self.tool_calls_used >= self.max_tool_calls:
            reason = (
                f"Tool call limit exceeded: {self.tool_calls_used}/{self.max_tool_calls} calls made"
            )
            self.is_exceeded = True
            self.exceeded_reason = reason
            
            if raise_on_exceeded:
                logger.error(reason)
                raise BudgetExceededError(reason)
            
            return BudgetStatus(
                ok=False,
                reason=reason,
                report=self._build_report(elapsed),
            )
        
        if self.consecutive_failures >= self.max_consecutive_failures:
            reason = (
                f"Consecutive failure limit exceeded: {self.consecutive_failures}/{self.max_consecutive_failures} failures"
            )
            self.is_exceeded = True
            self.exceeded_reason = reason
            
            if raise_on_exceeded:
                logger.error(reason)
                raise BudgetExceededError(reason)
            
            return BudgetStatus(
                ok=False,
                reason=reason,
                report=self._build_report(elapsed),
            )
        
        # All checks passed
        return BudgetStatus(
            ok=True,
            reason=None,
            report=self._build_report(elapsed),
        )
    
    def get_report(self) -> dict:
        """
        Get comprehensive usage report.
        
        Returns:
            Dictionary with all usage metrics and percentages
        """
        elapsed = self.get_wall_clock_elapsed()
        return self._build_report(elapsed)
    
    def _build_report(self, elapsed: float) -> dict:
        """
        Build usage report dictionary.
        
        Args:
            elapsed: Wall clock seconds elapsed
        
        Returns:
            Detailed usage report
        """
        tokens_pct = (self.tokens_used / self.max_tokens * 100) if self.max_tokens > 0 else 0
        time_pct = (elapsed / self.max_wall_clock_seconds * 100) if self.max_wall_clock_seconds > 0 else 0
        calls_pct = (self.tool_calls_used / self.max_tool_calls * 100) if self.max_tool_calls > 0 else 0
        failure_pct = (
            (self.consecutive_failures / self.max_consecutive_failures * 100)
            if self.max_consecutive_failures > 0
            else 0
        )
        
        return {
            "tokens": {
                "used": self.tokens_used,
                "limit": self.max_tokens,
                "percent": round(tokens_pct, 1),
                "by_provider": dict(self.tokens_by_provider),
            },
            "wall_clock": {
                "elapsed": round(elapsed, 2),
                "limit": self.max_wall_clock_seconds,
                "percent": round(time_pct, 1),
            },
            "tool_calls": {
                "used": self.tool_calls_used,
                "limit": self.max_tool_calls,
                "percent": round(calls_pct, 1),
                "by_tool": dict(self.tool_calls_by_name),
            },
            "consecutive_failures": {
                "current": self.consecutive_failures,
                "limit": self.max_consecutive_failures,
                "percent": round(failure_pct, 1),
            },
            "exceeded": self.is_exceeded,
            "exceeded_reason": self.exceeded_reason,
        }
    
    def reset(self) -> None:
        """Reset all tracking for a new session."""
        logger.info("Resetting budget enforcer for new session")
        self.tokens_used = 0
        self.tokens_by_provider = {}
        self.tool_calls_used = 0
        self.tool_calls_by_name = {}
        self.consecutive_failures = 0
        self.wall_clock_start = time.time()
        self.is_exceeded = False
        self.exceeded_reason = None
