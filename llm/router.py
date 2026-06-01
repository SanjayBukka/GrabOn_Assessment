"""Multi-LLM router with fallback strategy."""

import json
import logging
import os
from typing import Optional, Any
from enum import Enum

from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from llm.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """Task types for LLM routing."""
    PLANNING = "PLANNING"
    DEAL_EXTRACTION = "DEAL_EXTRACTION"
    CLASSIFICATION = "CLASSIFICATION"
    FALLBACK_EXTRACTION = "FALLBACK_EXTRACTION"
    IMPOSSIBLE_DETECTION = "IMPOSSIBLE_DETECTION"


class LLMRouter:
    """Routes tasks to appropriate LLM providers with fallback strategy."""
    
    def __init__(self, cost_tracker: Optional[CostTracker] = None):
        """Initialize LLM router with all provider clients and cost tracker."""
        self.cost_tracker = cost_tracker or CostTracker()
        self.current_provider = None
        self.current_usage = None
        
        # Initialize LLM clients
        self._init_providers()
    
    def _init_providers(self):
        """Initialize all LLM provider clients."""
        # Groq providers
        groq_key = os.getenv("GROQ_API_KEY")
        self.groq_large = (
            ChatGroq(
                model="llama-3.3-70b-versatile",
                api_key=groq_key,
                temperature=0.7,
                timeout=30,
            )
            if groq_key
            else None
        )
        
        self.groq_small = (
            ChatGroq(
                model="llama-3.1-8b-instant",
                api_key=groq_key,
                temperature=0.3,
                timeout=30,
            )
            if groq_key
            else None
        )
        
        # Gemini providers
        gemini_key = os.getenv("GOOGLE_API_KEY")
        self.gemini_flash = (
            ChatGoogleGenerativeAI(
                model="gemini-2.0-flash",
                api_key=gemini_key,
                temperature=0.7,
                timeout=30,
            )
            if gemini_key
            else None
        )
        
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_key and not openrouter_key.startswith("your_"):
            from langchain_openai import ChatOpenAI

            self.openrouter = ChatOpenAI(
                model="meta-llama/llama-3.2-3b-instruct:free",
                openai_api_key=openrouter_key,
                openai_api_base="https://openrouter.ai/api/v1",
                temperature=0.3,
                timeout=30,
            )
        else:
            self.openrouter = None

    def get_llm(self, task_type: str) -> Any:
        """Get the primary LLM for a task type."""
        task = TaskType(task_type.upper())
        
        if task == TaskType.PLANNING:
            if self.groq_large:
                return self.groq_large
            raise ValueError("Groq provider not configured")
        
        elif task == TaskType.DEAL_EXTRACTION:
            if self.openrouter:
                return self.openrouter
            elif self.groq_large:
                logger.warning("OpenRouter unavailable, falling back to Groq for extraction")
                return self.groq_large
            elif self.gemini_flash:
                logger.warning("OpenRouter/Groq unavailable, using Gemini for extraction")
                return self.gemini_flash
            raise ValueError("No extraction provider available")
        
        elif task == TaskType.CLASSIFICATION:
            if self.groq_small:
                return self.groq_small
            elif self.groq_large:
                logger.warning("Groq small unavailable, using large for classification")
                return self.groq_large
            raise ValueError("No classification provider available")
        
        elif task == TaskType.FALLBACK_EXTRACTION:
            if self.openrouter:
                return self.openrouter
            elif self.groq_small:
                logger.warning("OpenRouter unavailable, using Groq small for fallback")
                return self.groq_small
            raise ValueError("No fallback provider available")
        
        elif task == TaskType.IMPOSSIBLE_DETECTION:
            if self.openrouter:
                logger.info("Using OpenRouter for detection task")
                return self.openrouter
            elif self.groq_large:
                logger.info("Using Groq large fallback for detection task")
                return self.groq_large
            raise ValueError("No detection provider available")
        
        raise ValueError(f"Unknown task type: {task}")
    
    def call_with_tracking(
        self,
        task_type: str,
        prompt: str,
        max_tokens: int = 2048,
    ) -> tuple[str, int, float, str]:
        """Call LLM with tracking and fallback strategy."""
        task = TaskType(task_type.upper())
        
        # Primary attempt
        try:
            llm = self.get_llm(task_type)
            provider_name = self._get_provider_name(llm, task)
            
            response = llm.invoke([HumanMessage(content=prompt)])
            response_text = response.content
            
            # Estimate tokens (rough approximation)
            input_tokens = len(prompt.split()) * 1.3  # ~1.3 tokens per word
            output_tokens = len(response_text.split()) * 1.3
            input_tokens = int(input_tokens)
            output_tokens = int(output_tokens)
            
            # Track cost
            cost_provider = self._get_cost_provider_name(provider_name)
            call_cost = self.cost_tracker.record_call(
                provider=cost_provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                task_type=task.value,
            )
            
            logger.info(
                f"LLM call: {task} → {provider_name} "
                f"({input_tokens + output_tokens} tokens, ${call_cost.cost_usd:.6f})"
            )
            
            return response_text, input_tokens + output_tokens, call_cost.cost_usd, provider_name
        
        except Exception as e:
            logger.error(f"Primary LLM failed for {task}: {e}")
            
            # Fallback attempt
            if task == TaskType.DEAL_EXTRACTION:
                return self._fallback_extraction(prompt, max_tokens)
            elif task == TaskType.PLANNING:
                return self._fallback_planning(prompt, max_tokens)
            else:
                raise
    
    def _fallback_extraction(
        self,
        prompt: str,
        max_tokens: int,
    ) -> tuple[str, int, float, str]:
        """Fallback for deal extraction when primary fails."""
        logger.info("Attempting fallback extraction")
        fallback_chain = [
            ("Groq", self.groq_small or self.groq_large, "groq"),
            ("Gemini-Flash", self.gemini_flash, "gemini_flash"),
        ]

        for provider_name, llm, cost_provider in fallback_chain:
            if not llm:
                continue
            try:
                response = llm.invoke([HumanMessage(content=prompt)])
                response_text = response.content
                
                input_tokens = len(prompt.split()) * 1.3
                output_tokens = len(response_text.split()) * 1.3
                input_tokens = int(input_tokens)
                output_tokens = int(output_tokens)
                
                call_cost = self.cost_tracker.record_call(
                    provider=cost_provider,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    task_type=TaskType.DEAL_EXTRACTION.value,
                )
                
                logger.info(f"Fallback extraction succeeded with {provider_name}")
                return response_text, input_tokens + output_tokens, call_cost.cost_usd, provider_name
            except Exception as e:
                logger.warning(f"Fallback extraction failed with {provider_name}: {e}")

        raise ValueError("No extraction fallback provider available")
    
    def _fallback_planning(
        self,
        prompt: str,
        max_tokens: int,
    ) -> tuple[str, int, float, str]:
        """Fallback for planning when primary fails."""
        logger.info("Attempting fallback planning with alternate provider")
        if self.gemini_flash:
            try:
                response = self.gemini_flash.invoke([HumanMessage(content=prompt)])
                response_text = response.content

                input_tokens = int(len(prompt.split()) * 1.3)
                output_tokens = int(len(response_text.split()) * 1.3)

                call_cost = self.cost_tracker.record_call(
                    provider="gemini_flash",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    task_type=TaskType.PLANNING.value,
                )

                logger.info("Fallback planning succeeded with Gemini Flash")
                return response_text, input_tokens + output_tokens, call_cost.cost_usd, "Gemini-Flash"
            except Exception as e:
                logger.warning(f"Gemini planning fallback failed: {e}")

        if self.openrouter:
            try:
                response = self.openrouter.invoke([HumanMessage(content=prompt)])
                response_text = response.content

                input_tokens = int(len(prompt.split()) * 1.3)
                output_tokens = int(len(response_text.split()) * 1.3)

                call_cost = self.cost_tracker.record_call(
                    provider="openrouter",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    task_type=TaskType.PLANNING.value,
                )

                logger.info("Fallback planning succeeded with OpenRouter")
                return response_text, input_tokens + output_tokens, call_cost.cost_usd, "OpenRouter"
            except Exception as e:
                logger.warning(f"OpenRouter planning fallback failed: {e}")

        if self.groq_small:
            try:
                response = self.groq_small.invoke([HumanMessage(content=prompt)])
                response_text = response.content
                
                input_tokens = int(len(prompt.split()) * 1.3)
                output_tokens = int(len(response_text.split()) * 1.3)
                
                call_cost = self.cost_tracker.record_call(
                    provider="groq",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    task_type=TaskType.PLANNING.value,
                )
                
                logger.info(f"Fallback planning succeeded with Groq")
                return response_text, input_tokens + output_tokens, call_cost.cost_usd, "Groq"
            except Exception as e:
                logger.error(f"Groq planning fallback failed: {e}")

        raise ValueError("No planning fallback provider available")
    
    def _get_provider_name(self, llm: Any, task: TaskType) -> str:
        """Determine provider name from LLM instance."""
        if llm == self.groq_large:
            return "Groq-Large"
        elif llm == self.groq_small:
            return "Groq-Small"
        elif llm == self.gemini_flash:
            return "Gemini-Flash"
        elif llm == self.openrouter:
            return "OpenRouter"
        return "Unknown"

    def _get_cost_provider_name(self, provider_name: str) -> str:
        """Map routed provider names to cost tracker keys."""
        provider = provider_name.lower()
        if provider.startswith("groq"):
            return "groq"
        if provider.startswith("gemini"):
            return "gemini_flash"
        if provider.startswith("openrouter"):
            return "openrouter"
        return provider

    def shadow_test(self, prompt: str, task_type: str) -> dict:
        """Run a prompt through the primary provider and one shadow provider."""
        primary_response, p_tokens, p_cost, p_provider = self.call_with_tracking(
            task_type=task_type,
            prompt=prompt,
        )

        result = {
            "primary": {
                "provider": p_provider,
                "response": primary_response,
                "tokens": p_tokens,
                "cost": p_cost,
            }
        }

        secondary_llm = self._get_shadow_llm(task_type, p_provider)
        if not secondary_llm:
            return result

        try:
            task = TaskType(task_type.upper())
            secondary_response = secondary_llm.invoke([HumanMessage(content=prompt)])
            secondary_text = secondary_response.content
            result["secondary"] = {
                "provider": self._get_provider_name(secondary_llm, task),
                "response": secondary_text,
            }
            result["agreement"] = primary_response[:100] == secondary_text[:100]
        except Exception as e:
            logger.warning(f"Shadow test secondary provider failed: {e}")

        return result

    def _get_shadow_llm(self, task_type: str, primary_provider: str) -> Any:
        """Choose a non-primary provider for shadow testing."""
        task = TaskType(task_type.upper())

        if task == TaskType.DEAL_EXTRACTION:
            candidates = [self.groq_small, self.groq_large, self.openrouter]
        elif task == TaskType.PLANNING:
            candidates = [self.gemini_flash, self.openrouter, self.groq_small]
        elif task == TaskType.CLASSIFICATION:
            candidates = [self.groq_large, self.gemini_flash]
        elif task == TaskType.IMPOSSIBLE_DETECTION:
            candidates = [self.groq_large, self.openrouter]
        else:
            candidates = [self.groq_small, self.openrouter, self.gemini_flash]

        for candidate in candidates:
            if candidate and self._get_provider_name(candidate, task) != primary_provider:
                return candidate

        return None
    
    def get_cost_summary(self) -> dict:
        """Get cost summary from tracker."""
        return self.cost_tracker.get_summary()
