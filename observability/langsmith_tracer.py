"""
LangSmith integration for tracing agent execution.

Wraps agent operations in LangSmith traces for full observability.
Provides decorators and utilities for tracing:
- Full agent session (parent trace)
- Per-merchant loops (child traces)
- Individual tool calls (grandchild traces)
- LLM calls with cost tracking

Traces are viewable at: https://smith.langchain.com
"""

import logging
import os
from functools import wraps
from typing import Any, Callable, Optional

from langsmith import traceable

logger = logging.getLogger(__name__)


class LangSmithTracer:
    """
    LangSmith tracing integration for agent observability.
    
    Provides decorators and utilities for tracing agent execution
    with full context tags for session, merchant, tool, and LLM operations.
    """
    
    def __init__(self):
        """Initialize LangSmith tracer."""
        self.enabled = os.getenv("LANGCHAIN_TRACING_V2", "true").lower() == "true"
        self.project = os.getenv("LANGCHAIN_PROJECT", "grabon-audit-agent")
        
        if self.enabled:
            logger.info(f"LangSmith tracing enabled for project: {self.project}")
        else:
            logger.info("LangSmith tracing disabled")
    
    def trace_session(self, run_name: str = "audit_session"):
        """
        Decorator to trace entire agent session.
        
        Usage:
            @tracer.trace_session("audit_session")
            async def run(merchants):
                ...
        
        Args:
            run_name: Name of the session trace
        """
        def decorator(func: Callable) -> Callable:
            if not self.enabled:
                return func
            
            @traceable(
                name=run_name,
                run_type="chain",
                tags=["agent", "session", "audit"],
            )
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                logger.info(f"Starting traced session: {run_name}")
                result = await func(*args, **kwargs)
                logger.info(f"Completed traced session: {run_name}")
                return result
            
            @traceable(
                name=run_name,
                run_type="chain",
                tags=["agent", "session", "audit"],
            )
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                logger.info(f"Starting traced session: {run_name}")
                result = func(*args, **kwargs)
                logger.info(f"Completed traced session: {run_name}")
                return result
            
            # Return async or sync based on original function
            import asyncio
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper
        
        return decorator
    
    def trace_merchant(self, merchant_id: str, merchant_name: str):
        """
        Decorator to trace per-merchant audit loop.
        
        Usage:
            @tracer.trace_merchant("amazon", "Amazon")
            async def run_merchant(merchant_data):
                ...
        
        Args:
            merchant_id: ID of merchant
            merchant_name: Name of merchant
        """
        def decorator(func: Callable) -> Callable:
            if not self.enabled:
                return func
            
            run_name = f"merchant_{merchant_id}"
            
            @traceable(
                name=run_name,
                run_type="chain",
                tags=["agent", "merchant", merchant_id],
                metadata={
                    "merchant_id": merchant_id,
                    "merchant_name": merchant_name,
                },
            )
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                logger.info(f"Starting merchant trace: {merchant_name}")
                result = await func(*args, **kwargs)
                logger.info(f"Completed merchant trace: {merchant_name}")
                return result
            
            @traceable(
                name=run_name,
                run_type="chain",
                tags=["agent", "merchant", merchant_id],
                metadata={
                    "merchant_id": merchant_id,
                    "merchant_name": merchant_name,
                },
            )
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                logger.info(f"Starting merchant trace: {merchant_name}")
                result = func(*args, **kwargs)
                logger.info(f"Completed merchant trace: {merchant_name}")
                return result
            
            import asyncio
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper
        
        return decorator
    
    def trace_tool(self, tool_name: str, merchant_id: str = ""):
        """
        Decorator to trace individual tool execution.
        
        Usage:
            @tracer.trace_tool("scrape_html", "amazon")
            def scrape_html(url):
                ...
        
        Args:
            tool_name: Name of tool
            merchant_id: Optional merchant ID
        """
        def decorator(func: Callable) -> Callable:
            if not self.enabled:
                return func
            
            run_name = f"tool_{tool_name}"
            if merchant_id:
                run_name = f"tool_{tool_name}_{merchant_id}"
            
            @traceable(
                name=run_name,
                run_type="tool",
                tags=["tool", tool_name] + ([f"merchant_{merchant_id}"] if merchant_id else []),
                metadata={
                    "tool_name": tool_name,
                    "merchant_id": merchant_id,
                },
            )
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                logger.debug(f"Executing traced tool: {tool_name}")
                result = await func(*args, **kwargs)
                return result
            
            @traceable(
                name=run_name,
                run_type="tool",
                tags=["tool", tool_name] + ([f"merchant_{merchant_id}"] if merchant_id else []),
                metadata={
                    "tool_name": tool_name,
                    "merchant_id": merchant_id,
                },
            )
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                logger.debug(f"Executing traced tool: {tool_name}")
                result = func(*args, **kwargs)
                return result
            
            import asyncio
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper
        
        return decorator
    
    def trace_llm(
        self,
        task_type: str,
        provider: str = "",
        merchant_id: str = "",
    ):
        """
        Decorator to trace LLM calls with cost tracking.
        
        Usage:
            @tracer.trace_llm("PLANNING", "groq", "amazon")
            def call_llm(prompt):
                ...
        
        Args:
            task_type: Type of task (PLANNING, EXTRACTION, etc.)
            provider: LLM provider name
            merchant_id: Optional merchant ID
        """
        def decorator(func: Callable) -> Callable:
            if not self.enabled:
                return func
            
            run_name = f"llm_{task_type.lower()}"
            tags = ["llm", task_type.lower()]
            
            if provider:
                run_name = f"llm_{task_type.lower()}_{provider}"
                tags.append(provider)
            
            if merchant_id:
                run_name = f"{run_name}_{merchant_id}"
                tags.append(f"merchant_{merchant_id}")
            
            @traceable(
                name=run_name,
                run_type="llm",
                tags=tags,
                metadata={
                    "task_type": task_type,
                    "provider": provider,
                    "merchant_id": merchant_id,
                },
            )
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                logger.debug(f"Executing traced LLM: {task_type} via {provider}")
                result = await func(*args, **kwargs)
                return result
            
            @traceable(
                name=run_name,
                run_type="llm",
                tags=tags,
                metadata={
                    "task_type": task_type,
                    "provider": provider,
                    "merchant_id": merchant_id,
                },
            )
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                logger.debug(f"Executing traced LLM: {task_type} via {provider}")
                result = func(*args, **kwargs)
                return result
            
            import asyncio
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper
        
        return decorator
    
    def trace_phase(
        self,
        phase: str,
        merchant_id: str = "",
    ):
        """
        Decorator to trace agent loop phases (PLAN/ACT/OBSERVE/DECIDE).
        
        Usage:
            @tracer.trace_phase("PLAN", "amazon")
            def plan_phase(merchant):
                ...
        
        Args:
            phase: Phase name (PLAN, ACT, OBSERVE, DECIDE)
            merchant_id: Optional merchant ID
        """
        def decorator(func: Callable) -> Callable:
            if not self.enabled:
                return func
            
            run_name = f"phase_{phase.lower()}"
            if merchant_id:
                run_name = f"{run_name}_{merchant_id}"
            
            @traceable(
                name=run_name,
                run_type="chain",
                tags=["phase", phase.lower()] + ([f"merchant_{merchant_id}"] if merchant_id else []),
                metadata={
                    "phase": phase,
                    "merchant_id": merchant_id,
                },
            )
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                logger.debug(f"Executing phase: {phase}")
                result = await func(*args, **kwargs)
                return result
            
            @traceable(
                name=run_name,
                run_type="chain",
                tags=["phase", phase.lower()] + ([f"merchant_{merchant_id}"] if merchant_id else []),
                metadata={
                    "phase": phase,
                    "merchant_id": merchant_id,
                },
            )
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                logger.debug(f"Executing phase: {phase}")
                result = func(*args, **kwargs)
                return result
            
            import asyncio
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper
        
        return decorator


# Global tracer instance
_global_tracer = LangSmithTracer()


def get_tracer() -> LangSmithTracer:
    """Get the global LangSmith tracer instance."""
    return _global_tracer


def trace_session(run_name: str = "audit_session"):
    """Module-level trace_session decorator."""
    return _global_tracer.trace_session(run_name)


def trace_merchant(merchant_id: str, merchant_name: str):
    """Module-level trace_merchant decorator."""
    return _global_tracer.trace_merchant(merchant_id, merchant_name)


def trace_tool(tool_name: str, merchant_id: str = ""):
    """Module-level trace_tool decorator."""
    return _global_tracer.trace_tool(tool_name, merchant_id)


def trace_llm(task_type: str, provider: str = "", merchant_id: str = ""):
    """Module-level trace_llm decorator."""
    return _global_tracer.trace_llm(task_type, provider, merchant_id)


def trace_phase(phase: str, merchant_id: str = ""):
    """Module-level trace_phase decorator."""
    return _global_tracer.trace_phase(phase, merchant_id)
