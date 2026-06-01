"""Cost tracking and billing for LLM provider calls."""

import os
from typing import Optional
from pydantic import BaseModel


class ProviderCost(BaseModel):
    """Cost configuration for a single LLM provider."""
    provider: str
    input_cost_per_million: float  # USD per 1M input tokens
    output_cost_per_million: float  # USD per 1M output tokens


class CallCost(BaseModel):
    """Cost of a single LLM call."""
    provider: str
    task_type: str = "unknown"
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float


class CostTracker:
    """Tracks token consumption and costs across LLM providers."""
    
    def __init__(self):
        """Initialize cost tracker with provider configs from .env."""
        self.providers = {
            "groq": ProviderCost(
                provider="groq",
                input_cost_per_million=float(
                    os.getenv("GROQ_INPUT_COST", "0.05")
                ),
                output_cost_per_million=float(
                    os.getenv("GROQ_OUTPUT_COST", "0.08")
                ),
            ),
            "gemini_flash": ProviderCost(
                provider="gemini_flash",
                input_cost_per_million=float(
                    os.getenv("GEMINI_INPUT_COST", "0.075")
                ),
                output_cost_per_million=float(
                    os.getenv("GEMINI_OUTPUT_COST", "0.30")
                ),
            ),
            "openrouter": ProviderCost(
                provider="openrouter",
                input_cost_per_million=float(
                    os.getenv("OPENROUTER_INPUT_COST", "0.10")
                ),
                output_cost_per_million=float(
                    os.getenv("OPENROUTER_OUTPUT_COST", "0.20")
                ),
            ),
        }
        
        # Track cumulative costs and tokens
        self.total_tokens_by_provider: dict[str, int] = {
            p: 0 for p in self.providers.keys()
        }
        self.total_cost_by_provider: dict[str, float] = {
            p: 0.0 for p in self.providers.keys()
        }
        self.total_cost_by_task: dict[str, float] = {}
        self.total_tokens_by_task: dict[str, int] = {}
        self.total_tokens_all: int = 0
        self.total_cost_all: float = 0.0
        self.call_count: int = 0
        self.call_history: list[CallCost] = []
    
    def calculate_cost(
        self,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        task_type: str = "unknown",
    ) -> CallCost:
        """Calculate cost for a single LLM call."""
        if provider not in self.providers:
            raise ValueError(f"Unknown provider: {provider}")
        
        config = self.providers[provider]
        total_tokens = input_tokens + output_tokens
        
        # Cost = (tokens / 1,000,000) * cost_per_million
        input_cost = (input_tokens / 1_000_000) * config.input_cost_per_million
        output_cost = (output_tokens / 1_000_000) * config.output_cost_per_million
        total_cost = input_cost + output_cost
        
        call = CallCost(
            provider=provider,
            task_type=task_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=total_cost,
        )
        
        return call
    
    def record_call(
        self,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        task_type: str = "unknown",
    ) -> CallCost:
        """Record a single LLM call and update totals."""
        call_cost = self.calculate_cost(provider, input_tokens, output_tokens, task_type)
        
        # Update tracking
        self.total_tokens_by_provider[provider] += call_cost.total_tokens
        self.total_cost_by_provider[provider] += call_cost.cost_usd
        if task_type not in self.total_cost_by_task:
            self.total_cost_by_task[task_type] = 0.0
            self.total_tokens_by_task[task_type] = 0
        self.total_cost_by_task[task_type] += call_cost.cost_usd
        self.total_tokens_by_task[task_type] += call_cost.total_tokens
        self.total_tokens_all += call_cost.total_tokens
        self.total_cost_all += call_cost.cost_usd
        self.call_count += 1
        self.call_history.append(call_cost)
        
        return call_cost
    
    def get_summary(self) -> dict:
        """Get cost summary across all providers."""
        return {
            "total_calls": self.call_count,
            "total_tokens": self.total_tokens_all,
            "total_cost_usd": round(self.total_cost_all, 6),
            "by_provider": {
                provider: {
                    "tokens": self.total_tokens_by_provider[provider],
                    "cost_usd": round(self.total_cost_by_provider[provider], 6),
                }
                for provider in self.providers.keys()
            },
            "by_task_type": {
                task_type: {
                    "tokens": self.total_tokens_by_task[task_type],
                    "cost_usd": round(self.total_cost_by_task[task_type], 6),
                }
                for task_type in sorted(self.total_cost_by_task.keys())
            },
            "providers_used": [
                p for p in self.providers.keys()
                if self.total_tokens_by_provider[p] > 0
            ],
        }
    
    def reset(self):
        """Reset all tracking for a new session."""
        for provider in self.providers.keys():
            self.total_tokens_by_provider[provider] = 0
            self.total_cost_by_provider[provider] = 0.0
        self.total_cost_by_task = {}
        self.total_tokens_by_task = {}
        self.total_tokens_all = 0
        self.total_cost_all = 0.0
        self.call_count = 0
        self.call_history = []
