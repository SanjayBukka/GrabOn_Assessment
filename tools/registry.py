"""
Tool registry with dynamic discovery and execution.

Manages tool registration, execution with timeout enforcement,
and tracks per-tool statistics (call counts, failures).
"""

import asyncio
import inspect
import logging
import time
from typing import Any, Callable, Optional
from functools import wraps

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ToolMetadata(BaseModel):
    """Metadata for a registered tool."""
    name: str
    description: str
    schema: Optional[type] = None  # Pydantic schema for input validation
    timeout_seconds: int = 30
    cost_annotation: str = ""  # e.g., "HIGH", "LOW", "FREE"
    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    
    class Config:
        arbitrary_types_allowed = True


class ToolResult(BaseModel):
    """Result from tool execution."""
    success: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    error_type: Optional[str] = None  # TRANSIENT, PERMANENT, RATE_LIMIT, NOT_FOUND, TIMEOUT
    latency_ms: float = 0.0
    tool_name: str = ""


class ToolRegistry:
    """
    Manages tool registration, discovery, and execution.
    
    Tools are registered via @registry.register() decorator.
    Supports dynamic discovery and enforces timeouts.
    """
    
    def __init__(self):
        """Initialize empty tool registry."""
        self._tools: dict[str, Callable] = {}
        self._metadata: dict[str, ToolMetadata] = {}
    
    def register(
        self,
        name: str,
        description: str = "",
        timeout_seconds: int = 30,
        cost_annotation: str = "",
        schema: Optional[type] = None,
    ):
        """
        Decorator to register a tool.
        
        Args:
            name: Unique tool name
            description: What the tool does
            timeout_seconds: Max execution time
            cost_annotation: e.g., "HIGH", "LOW", "FREE"
            schema: Pydantic schema for input validation
        
        Example:
            @registry.register("scrape_html", "Scrapes HTML from URL", timeout_seconds=30)
            def scrape_html(url: str) -> dict:
                ...
        """
        def decorator(func: Callable) -> Callable:
            self._tools[name] = func
            self._metadata[name] = ToolMetadata(
                name=name,
                description=description,
                timeout_seconds=timeout_seconds,
                cost_annotation=cost_annotation,
                schema=schema,
            )
            logger.info(f"Registered tool: {name} ({description})")
            return func
        
        return decorator
    
    def get_tool(self, name: str) -> Optional[Callable]:
        """
        Get a registered tool by name.
        
        Args:
            name: Tool name
        
        Returns:
            Tool function or None if not found
        """
        return self._tools.get(name)
    
    def list_tools(self) -> list[ToolMetadata]:
        """
        Get metadata for all registered tools.
        
        Returns:
            List of ToolMetadata
        """
        return list(self._metadata.values())
    
    async def execute(
        self,
        name: str,
        **kwargs,
    ) -> ToolResult:
        """
        Execute a tool with timeout enforcement.
        
        Args:
            name: Tool name
            **kwargs: Arguments to pass to tool
        
        Returns:
            ToolResult with success/error info
        """
        if name not in self._tools:
            return ToolResult(
                success=False,
                tool_name=name,
                error=f"Tool '{name}' not found",
                error_type="PERMANENT",
            )
        
        tool_func = self._tools[name]
        metadata = self._metadata[name]
        
        start_time = time.time()
        
        try:
            # Check if function is async
            if asyncio.iscoroutinefunction(tool_func):
                # For async functions, run with timeout
                result = await asyncio.wait_for(
                    tool_func(**kwargs),
                    timeout=metadata.timeout_seconds,
                )
            else:
                # For sync functions, run in executor to avoid blocking
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: tool_func(**kwargs)),
                    timeout=metadata.timeout_seconds,
                )
            
            # Record success
            latency_ms = (time.time() - start_time) * 1000
            metadata.call_count += 1
            metadata.success_count += 1
            metadata.total_latency_ms += latency_ms
            
            return ToolResult(
                success=True,
                data=result,
                latency_ms=latency_ms,
                tool_name=name,
            )
        
        except asyncio.TimeoutError:
            latency_ms = (time.time() - start_time) * 1000
            metadata.call_count += 1
            metadata.failure_count += 1
            metadata.total_latency_ms += latency_ms
            
            return ToolResult(
                success=False,
                tool_name=name,
                error=f"Tool execution timed out after {metadata.timeout_seconds}s",
                error_type="TIMEOUT",
                latency_ms=latency_ms,
            )
        
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            metadata.call_count += 1
            metadata.failure_count += 1
            metadata.total_latency_ms += latency_ms
            
            # Classify error type
            error_msg = str(e)
            error_type = "TRANSIENT"
            
            if "404" in error_msg or "not found" in error_msg.lower():
                error_type = "NOT_FOUND"
            elif "403" in error_msg or "429" in error_msg:
                error_type = "RATE_LIMIT"
            elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                error_type = "TIMEOUT"
            
            logger.error(f"Tool {name} failed: {error_msg}")
            
            return ToolResult(
                success=False,
                tool_name=name,
                error=error_msg,
                error_type=error_type,
                latency_ms=latency_ms,
            )
    
    async def _execute_async(
        self,
        func: Callable,
        metadata: ToolMetadata,
        kwargs: dict,
    ) -> Any:
        """
        Execute async tool with timeout.
        
        Args:
            func: Async tool function
            metadata: Tool metadata (contains timeout)
            kwargs: Arguments
        
        Returns:
            Tool result
        
        Raises:
            TimeoutError: If execution exceeds timeout
        """
        try:
            result = await asyncio.wait_for(
                func(**kwargs),
                timeout=metadata.timeout_seconds,
            )
            return result
        except asyncio.TimeoutError:
            raise
    
    def get_stats(self) -> dict:
        """
        Get statistics for all tools.
        
        Returns:
            Dictionary with per-tool stats
        """
        stats = {}
        for name, metadata in self._metadata.items():
            avg_latency = (
                metadata.total_latency_ms / metadata.call_count
                if metadata.call_count > 0
                else 0.0
            )
            
            stats[name] = {
                "call_count": metadata.call_count,
                "success_count": metadata.success_count,
                "failure_count": metadata.failure_count,
                "success_rate": (
                    metadata.success_count / metadata.call_count
                    if metadata.call_count > 0
                    else 0.0
                ),
                "avg_latency_ms": round(avg_latency, 2),
                "total_latency_ms": round(metadata.total_latency_ms, 2),
                "description": metadata.description,
                "cost": metadata.cost_annotation,
            }
        
        return {
            "total_tools": len(self._metadata),
            "tools": stats,
        }
    
    def reset_stats(self):
        """Reset all tool statistics."""
        for metadata in self._metadata.values():
            metadata.call_count = 0
            metadata.success_count = 0
            metadata.failure_count = 0
            metadata.total_latency_ms = 0.0


# Global registry instance
_global_registry = ToolRegistry()


def register(
    name: str,
    description: str = "",
    timeout_seconds: int = 30,
    cost_annotation: str = "",
    schema: Optional[type] = None,
):
    """
    Module-level register function for convenient decorator use.
    
    Usage:
        @register("tool_name", "Description here")
        def my_tool(arg: str) -> dict:
            ...
    """
    return _global_registry.register(
        name=name,
        description=description,
        timeout_seconds=timeout_seconds,
        cost_annotation=cost_annotation,
        schema=schema,
    )


def get_registry() -> ToolRegistry:
    """Get the global tool registry instance."""
    return _global_registry
