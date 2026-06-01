"""
Core agent loop implementation with explicit PLAN/ACT/OBSERVE/DECIDE phases.

This is the main agent execution engine that orchestrates the audit process.
The AgentLoop class implements a clear 4-phase decision loop:
- PLAN: Create strategy using LLM planner
- ACT: Execute the next planned tool
- OBSERVE: Analyze the result
- DECIDE: Determine next action (continue, retry, switch tool, replan, or fail)
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from agent.state import (
    AgentState, AgentIteration, Phase, MerchantResult,
)
from agent.budget import BudgetEnforcer, BudgetExceededError
from agent.planner import AgentPlanner, Plan
from tools.registry import ToolRegistry, ToolResult, get_registry
from observability.terminal_ui import TerminalUI
from observability.langsmith_tracer import trace_session, trace_phase, get_tracer

# Import tools to trigger registration in registry
import tools.scraper_html  # noqa: F401
import tools.google_cache  # noqa: F401
import tools.scraper_js  # noqa: F401
import tools.deal_extractor  # noqa: F401
import tools.db_lookup  # noqa: F401
import tools.deal_classifier  # noqa: F401
import tools.unreliable_verifier  # noqa: F401

logger = logging.getLogger(__name__)


class AgentLoop:
    """
    Core agent loop with explicit PLAN/ACT/OBSERVE/DECIDE phases.
    
    This class orchestrates the audit of GrabOn deal pages by:
    1. Planning each merchant's audit strategy (LLM-based)
    2. Acting by executing planned tools with timeouts
    3. Observing the results and error classifications
    4. Deciding on next steps (continue, retry, fallback, replan, or fail)
    
    Budget is enforced at every iteration to prevent runaway execution.
    """
    
    def __init__(self, ui: Optional[TerminalUI] = None):
        """
        Initialize the agent loop.
        
        Args:
            ui: Optional TerminalUI for live updates during execution
        """
        self.ui = ui
        self.registry = get_registry()
        self.budget_enforcer = BudgetEnforcer()
        self.planner = AgentPlanner()
        self.tracer = get_tracer()
        self.state: Optional[AgentState] = None
    
    @trace_session("audit_session")
    async def run(self, merchants: List[Dict]) -> AgentState:
        """
        Run the agent audit loop for all merchants.
        
        For each merchant, executes the full PLAN/ACT/OBSERVE/DECIDE loop.
        Enforces budget limits globally and halts if exceeded.
        
        Args:
            merchants: List of merchant dicts with 'id', 'name', 'url' keys
            
        Returns:
            Final AgentState containing all iterations, results, and audit report
            
        Raises:
            BudgetExceededError: If any resource limit is breached
        """
        # Initialize global state
        self.state = AgentState(
            session_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
            start_time=datetime.now(),
            merchants_total=len(merchants),
            merchants_completed=0,
            merchants_failed=0,
            current_merchant="",
            iterations=[],
            total_tokens=0,
            total_cost_usd=0.0,
            total_tool_calls=0,
            consecutive_failures=0,
            budget_exceeded=False,
            final_report=None,
        )
        
        logger.info(f"Starting audit loop for {len(merchants)} merchants")
        logger.info(f"Session ID: {self.state.session_id}")
        
        if self.ui:
            self.ui.update(self.state)
        
        # Process each merchant
        for merchant in merchants:
            try:
                # Check budget before processing merchant
                budget_status = self.budget_enforcer.check_limits(raise_on_exceeded=False)
                if not budget_status.ok:
                    logger.error(f"Budget limit breached before merchant: {budget_status.reason}")
                    self.state.budget_exceeded = True
                    break
                
                # Process this merchant with full PLAN/ACT/OBSERVE/DECIDE loop
                await self._run_merchant(merchant)
                
            except BudgetExceededError as e:
                logger.error(f"Budget enforcement error: {e}")
                self.state.budget_exceeded = True
                break
            except Exception as e:
                logger.error(f"Error processing merchant {merchant.get('id')}: {e}", exc_info=True)
                self.state.merchants_failed += 1
                self.state.consecutive_failures += 1
                
                # Halt if too many consecutive failures
                if self.state.consecutive_failures >= 5:
                    logger.error("Max consecutive failures reached, halting agent")
                    break
            finally:
                if self.ui:
                    self.ui.update(self.state)
        
        # Generate and save final report
        self.state.final_report = self._generate_report()
        self._save_report()
        
        logger.info(f"Audit complete. Session: {self.state.session_id}")
        logger.info(f"Completed: {self.state.merchants_completed}, Failed: {self.state.merchants_failed}")
        logger.info(f"Total cost: ${self.state.total_cost_usd:.4f}")
        
        if self.ui:
            self.ui.print_summary(self.state)
        
        return self.state
    
    async def _run_merchant(self, merchant: Dict) -> Optional[MerchantResult]:
        """
        Run the full PLAN/ACT/OBSERVE/DECIDE loop for one merchant.
        
        Executes a complete audit of a single merchant by:
        1. Creating an initial plan
        2. For each step in plan: ACT → OBSERVE → DECIDE
        3. Replanning when tools fail (with fallback strategies)
        4. Retrying transient failures with exponential backoff
        5. Stopping after max consecutive failures
        
        Args:
            merchant: Merchant dict with 'id', 'name', 'url' keys
            
        Returns:
            MerchantResult with scraped/classified deals or error status
        """
        merchant_id = merchant.get("id", "")
        merchant_name = merchant.get("name", "")
        merchant_url = merchant.get("url", "")
        
        logger.info(f"Starting merchant audit: {merchant_name}")
        self.state.current_merchant = merchant_name
        
        # Initialize merchant result
        result = MerchantResult(
            merchant_id=merchant_id,
            name=merchant_name,
            url=merchant_url,
            db_deals=[],
            live_deals=[],
            classified_deals=[],
            status="in_progress",
            error_message=None,
            tool_calls_used=0,
            time_taken=0.0,
        )
        
        merchant_start = time.time()
        retry_count = 0
        current_plan = None
        step_in_plan = 0
        last_html = ""
        
        try:
            # Main loop: continue until plan complete or fatal error
            while True:
                # ==================== PHASE 1: PLAN ====================
                if current_plan is None:
                    current_plan = await self._phase_plan(
                        merchant_id, merchant_name, merchant_url
                    )
                    step_in_plan = 0
                    logger.debug(f"Created plan with steps: {[s.tool for s in current_plan.steps]}")
                
                # Check if plan is complete
                if step_in_plan >= len(current_plan.steps):
                    logger.info(f"Plan complete for {merchant_name}")
                    result.status = "completed"
                    self.state.merchants_completed += 1
                    self.state.consecutive_failures = 0
                    break
                
                plan_step = current_plan.steps[step_in_plan]
                tool_name = plan_step.tool
                
                # ==================== PHASE 2: ACT ====================
                tool_result = await self._phase_act(
                    merchant_id, merchant_name, tool_name, merchant_url, result, last_html
                )
                
                # Store HTML for extraction step
                if tool_result.success and tool_name in ["scrape_html", "google_cache", "scrape_js"]:
                    last_html = tool_result.data.get("html", "")
                    logger.debug(f"Stored {len(last_html)} bytes of HTML for next step")
                
                # ==================== PHASE 3: OBSERVE ====================
                observation = await self._phase_observe(tool_name, tool_result)
                
                # ==================== PHASE 4: DECIDE ====================
                decision = await self._phase_decide(
                    merchant_id, merchant_name, tool_name, tool_result,
                    current_plan, step_in_plan, retry_count
                )
                
                # EXECUTE DECISION
                if decision == "CONTINUE":
                    # Move to next step in plan
                    step_in_plan += 1
                    retry_count = 0
                    logger.debug(f"Continuing to step {step_in_plan + 1}")
                    
                elif decision.startswith("RETRY"):
                    # Retry same step with backoff
                    wait_time = 2 ** min(retry_count, 3)  # Cap at 8s
                    logger.info(f"Retrying {tool_name} in {wait_time}s (attempt {retry_count + 1})")
                    await asyncio.sleep(wait_time)
                    retry_count += 1
                    # Don't increment step_in_plan, retry same step
                    
                elif decision.startswith("SWITCH_TOOL:"):
                    # Switch to alternative tool
                    new_tool = decision.split(":")[1] if ":" in decision else "scrape_js"
                    logger.info(f"Switching from {tool_name} to {new_tool}")
                    current_plan.steps[step_in_plan].tool = new_tool
                    retry_count = 0
                    # Retry with new tool
                    
                elif decision == "REPLAN":
                    # Request full replan from planner
                    error_type = tool_result.error_type or "UNKNOWN"
                    logger.info(f"Replanning after {tool_name} failed with {error_type}")
                    current_plan = await self.planner.replan(
                        merchant_id=merchant_id,
                        merchant_name=merchant_name,
                        merchant_url=merchant_url,
                        failed_tool=tool_name,
                        error_type=error_type,
                        tokens_used=self.budget_enforcer.tokens_used,
                        max_tokens=self.budget_enforcer.max_tokens,
                        tool_calls_used=self.budget_enforcer.tool_calls_used,
                        max_tool_calls=self.budget_enforcer.max_tool_calls,
                    )
                    self._record_planner_usage()
                    step_in_plan = 0
                    retry_count = 0
                    logger.debug(f"Replanned: {[s.tool for s in current_plan.steps]}")
                    
                elif decision == "MERCHANT_FAILED":
                    # Fatal error - give up on merchant
                    logger.warning(f"Merchant {merchant_name} failed permanently after {tool_name}")
                    result.status = "error"
                    result.error_message = f"Tool {tool_name} failed with {tool_result.error_type}: {tool_result.error}"
                    self.state.merchants_failed += 1
                    self.state.consecutive_failures += 1
                    break
                
                # Check budget after EVERY iteration
                budget_status = self.budget_enforcer.check_limits(raise_on_exceeded=False)
                if not budget_status.ok:
                    logger.error(f"Budget limit exceeded: {budget_status.reason}")
                    self.state.budget_exceeded = True
                    raise BudgetExceededError(budget_status.reason)
        
        except BudgetExceededError:
            # Rethrow budget errors
            raise
        except Exception as e:
            logger.error(f"Error in merchant loop {merchant_name}: {e}", exc_info=True)
            result.status = "error"
            result.error_message = str(e)
            self.state.merchants_failed += 1
            self.state.consecutive_failures += 1
        
        finally:
            # Finalize result
            result.time_taken = time.time() - merchant_start
            result.tool_calls_used = self.state.total_tool_calls
            if result not in self.state.merchant_results:
                self.state.merchant_results.append(result)
            
            if self.ui:
                self.ui.update(self.state)
        
        return result
    
    @trace_phase("PLAN")
    async def _phase_plan(
        self, merchant_id: str, merchant_name: str, merchant_url: str
    ) -> Plan:
        """
        PLAN phase: Create audit plan using LLM-based planner.
        
        Calls the AgentPlanner to generate a step-by-step plan for auditing
        this merchant, taking into account available tools and budget constraints.
        
        Args:
            merchant_id: Merchant ID
            merchant_name: Merchant name
            merchant_url: Merchant URL
            
        Returns:
            Plan object with ordered list of tool execution steps
        """
        phase_start = time.time()
        logger.debug(f"PLAN phase for {merchant_name}")
        
        # Get budget context for planner
        tokens_used = self.budget_enforcer.tokens_used
        max_tokens = self.budget_enforcer.max_tokens
        tool_calls_used = self.budget_enforcer.tool_calls_used
        max_tool_calls = self.budget_enforcer.max_tool_calls
        
        # Create plan using LLM planner
        plan = await self.planner.create_plan(
            merchant_id=merchant_id,
            merchant_name=merchant_name,
            merchant_url=merchant_url,
            tokens_used=tokens_used,
            max_tokens=max_tokens,
            tool_calls_used=tool_calls_used,
            max_tool_calls=max_tool_calls,
        )
        self._record_planner_usage()
        
        # Record iteration
        iteration = AgentIteration(
            step_number=len(self.state.iterations) + 1,
            phase=Phase.PLAN,
            action=f"Created plan with {len(plan.steps)} steps",
            tool_called=None,
            observation=f"Steps: {[s.tool for s in plan.steps]}",
            decision="Execute plan steps sequentially",
            tokens_consumed=self.planner.last_tokens_used,
            wall_clock_time=time.time() - phase_start,
            llm_provider=self.planner.last_provider,
            cost_usd=self.planner.last_cost_usd,
        )
        self.state.iterations.append(iteration)
        
        return plan
    
    @trace_phase("ACT")
    async def _phase_act(
        self,
        merchant_id: str,
        merchant_name: str,
        tool_name: str,
        merchant_url: str,
        result: MerchantResult,
        last_html: str,
    ) -> ToolResult:
        """
        ACT phase: Execute the planned tool with timeout enforcement.
        
        Prepares tool parameters and executes the tool via the registry.
        Handles different tool types (scrapers, extractors, classifiers).
        
        Args:
            merchant_id: Merchant ID
            merchant_name: Merchant name
            tool_name: Tool to execute
            merchant_url: Merchant URL for scrapers
            result: Current MerchantResult tracking
            last_html: HTML from previous scraping step (for extractors)
            
        Returns:
            ToolResult with success/failure status and data/error info
        """
        phase_start = time.time()
        logger.debug(f"ACT phase: executing {tool_name}")
        
        # Prepare tool parameters based on tool type
        tool_params = {}
        
        if tool_name == "scrape_html":
            tool_params = {"url": merchant_url}
        elif tool_name == "google_cache":
            tool_params = {"original_url": merchant_url}
        elif tool_name == "scrape_js":
            tool_params = {"url": merchant_url}
        elif tool_name == "extract_deals":
            tool_params = {
                "html": last_html,
                "merchant_name": merchant_name,
                "merchant_id": merchant_id,
            }
        elif tool_name == "db_lookup":
            tool_params = {"merchant_id": merchant_id}
        elif tool_name == "classify_deals":
            tool_params = {
                "merchant_id": merchant_id,
                "db_deals": result.db_deals,
                "live_deals": result.live_deals,
            }
        elif tool_name == "verify_coupon":
            # Get first coupon code from live deals for verification
            coupon_code = result.live_deals[0].code if result.live_deals else "TEST"
            tool_params = {
                "merchant_id": merchant_id,
                "coupon_code": coupon_code,
            }
        
        # Execute tool via registry (with timeout enforcement)
        logger.info(f"Executing {tool_name} with params: merchant={merchant_id}")
        tool_result = await self.registry.execute(tool_name, **tool_params)
        
        # Update global tracking
        self.state.total_tool_calls += 1
        self.budget_enforcer.record_tool_call(tool_name, tool_result.success)
        result.tool_calls_used = self.state.total_tool_calls
        llm_tokens_used = 0
        llm_provider = ""
        llm_cost_usd = 0.0
        
        # Update result tracking based on tool outcome
        if tool_result.success:
            if tool_name == "extract_deals":
                result.live_deals = tool_result.data.get("deals", [])
                tokens_used = tool_result.data.get("tokens_used", 0)
                provider = tool_result.data.get("llm_provider_used", "unknown")
                cost_usd = tool_result.data.get("cost_usd", 0.0)
                llm_tokens_used = tokens_used
                llm_provider = provider
                llm_cost_usd = cost_usd
                if tokens_used:
                    self.budget_enforcer.record_tokens(tokens_used, provider)
                    self.state.total_tokens = self.budget_enforcer.tokens_used
                    self.state.total_cost_usd += cost_usd
                logger.info(f"Extracted {len(result.live_deals)} live deals")
            elif tool_name == "db_lookup":
                result.db_deals = tool_result.data.get("deals", [])
                logger.info(f"Retrieved {len(result.db_deals)} DB deals")
            elif tool_name == "classify_deals":
                result.classified_deals = tool_result.data.get("classified_deals", [])
                result.health_score = tool_result.data.get("merchant_health_score", 0.0)
                logger.info(f"Classified {len(result.classified_deals)} deals")
        
        # Record iteration
        iteration = AgentIteration(
            step_number=len(self.state.iterations) + 1,
            phase=Phase.ACT,
            action=f"Executed {tool_name}",
            tool_called=tool_name,
            observation="Awaiting result",
            decision="Analyze in OBSERVE phase",
            tokens_consumed=llm_tokens_used,
            wall_clock_time=time.time() - phase_start,
            llm_provider=llm_provider,
            cost_usd=llm_cost_usd,
        )
        self.state.iterations.append(iteration)
        
        return tool_result
    
    @trace_phase("OBSERVE")
    async def _phase_observe(self, tool_name: str, tool_result: ToolResult) -> str:
        """
        OBSERVE phase: Analyze tool execution result.
        
        Evaluates whether the tool succeeded, timed out, was rate-limited,
        received a not-found error, or experienced a permanent failure.
        This classification drives the DECIDE phase logic.
        
        Args:
            tool_name: Tool that was executed
            tool_result: Result from tool execution
            
        Returns:
            Observation string describing the result
        """
        phase_start = time.time()
        
        if tool_result.success:
            observation = f"{tool_name} succeeded in {tool_result.latency_ms}ms"
            logger.info(observation)
        else:
            observation = f"{tool_name} failed: {tool_result.error} (type: {tool_result.error_type})"
            logger.warning(observation)
        
        # Record iteration
        iteration = AgentIteration(
            step_number=len(self.state.iterations) + 1,
            phase=Phase.OBSERVE,
            action="Analyzed execution result",
            tool_called=tool_name,
            observation=observation,
            decision="Proceed to DECIDE for action selection",
            tokens_consumed=0,
            wall_clock_time=time.time() - phase_start,
            llm_provider="",
            cost_usd=0.0,
        )
        self.state.iterations.append(iteration)
        
        return observation
    
    @trace_phase("DECIDE")
    async def _phase_decide(
        self,
        merchant_id: str,
        merchant_name: str,
        tool_name: str,
        tool_result: ToolResult,
        current_plan: Plan,
        step_in_plan: int,
        retry_count: int,
    ) -> str:
        """
        DECIDE phase: Determine next action based on tool result.
        
        Implements the failure recovery decision tree:
        - SUCCESS: Continue to next step (or complete if last step)
        - TRANSIENT: Retry with exponential backoff (2^retry_count seconds)
        - RATE_LIMIT: Wait and retry
        - NOT_FOUND: Try cache (google_cache) or other fallback
        - TIMEOUT: Switch to slower tool (scrape_js) or fallback
        - PERMANENT: Request full replan with alternative tools
        
        Args:
            merchant_id: Merchant ID
            merchant_name: Merchant name
            tool_name: Tool that was executed
            tool_result: Result from execution
            current_plan: Current execution plan
            step_in_plan: Current step number in plan
            retry_count: Number of retries so far for this step
            
        Returns:
            Decision string matching one of:
            - "CONTINUE": Proceed to next step
            - "RETRY": Retry current step with backoff
            - "SWITCH_TOOL:alternative_tool": Try different tool
            - "REPLAN": Request replan from planner
            - "MERCHANT_FAILED": Give up on this merchant
        """
        phase_start = time.time()
        
        if tool_result.success:
            if tool_name in ["scrape_html", "google_cache"]:
                html = tool_result.data.get("html", "") if tool_result.data else ""
                if not html or len(html.strip()) < 100:
                    decision = "SWITCH_TOOL:scrape_js"
                    reasoning = "HTML too short/empty, switching to JS scraper"
                else:
                    is_last_step = step_in_plan >= len(current_plan.steps) - 1
                    if is_last_step:
                        decision = "CONTINUE"
                        reasoning = "Tool succeeded, plan complete"
                    else:
                        decision = "CONTINUE"
                        reasoning = "Tool succeeded, proceeding to next step"
            else:
                # Tool succeeded - proceed
                is_last_step = step_in_plan >= len(current_plan.steps) - 1
                if is_last_step:
                    decision = "CONTINUE"
                    reasoning = "Tool succeeded, plan complete"
                else:
                    decision = "CONTINUE"
                    reasoning = "Tool succeeded, proceeding to next step"
        
        elif tool_result.error_type == "TRANSIENT":
            # Transient errors (network hiccups, timeouts) - retry with backoff
            if retry_count < 3:
                decision = "RETRY"
                reasoning = f"Transient error, retrying (attempt {retry_count + 1})"
            else:
                decision = "REPLAN"
                reasoning = f"Max retries ({retry_count}) exceeded for transient errors"
        
        elif tool_result.error_type == "RATE_LIMIT":
            # Rate limited - wait and retry
            decision = "RETRY"
            reasoning = "Rate limited (429/403), waiting 30s before retry"
        
        elif tool_result.error_type == "NOT_FOUND":
            # Page not found - try cache if scraper
            if tool_name in ["scrape_html"]:
                decision = "SWITCH_TOOL:google_cache"
                reasoning = "Page not found (404), switching to Google Cache"
            elif tool_name == "google_cache":
                decision = "MERCHANT_FAILED"
                reasoning = "Page not found even in cache, merchant unavailable"
            else:
                decision = "REPLAN"
                reasoning = "Not-found error, replanning"
        
        elif tool_result.error_type == "TIMEOUT":
            # Timeout - try slower/alternative tool
            if tool_name == "scrape_html":
                decision = "SWITCH_TOOL:scrape_js"
                reasoning = "HTTP scrape timed out, switching to JS-capable scraper"
            elif tool_name == "scrape_js":
                decision = "SWITCH_TOOL:google_cache"
                reasoning = "JS scrape timed out, trying cache"
            else:
                decision = "REPLAN"
                reasoning = "Tool timeout, replanning with alternatives"
        
        elif tool_result.error_type == "PERMANENT":
            # Permanent errors - request replan
            decision = "REPLAN"
            reasoning = f"Permanent error in {tool_name}, replanning with alternatives"
        
        else:
            # Unknown error type - attempt replan
            decision = "REPLAN"
            reasoning = f"Unknown error type ({tool_result.error_type}), replanning"
        
        logger.info(f"DECIDE: {decision} ({reasoning})")
        
        # Record iteration
        iteration = AgentIteration(
            step_number=len(self.state.iterations) + 1,
            phase=Phase.DECIDE,
            action=f"Decided: {decision}",
            tool_called=tool_name,
            observation=tool_result.error or "Success",
            decision=decision,
            tokens_consumed=0,
            wall_clock_time=time.time() - phase_start,
            llm_provider="",
            cost_usd=0.0,
        )
        self.state.iterations.append(iteration)
        
        return decision
    
    def _generate_report(self) -> Dict:
        """
        Generate the final audit report as a dictionary.
        
        Aggregates statistics from the session including:
        - Session metadata (ID, duration, merchants processed)
        - Deal statistics (fresh, stale, missing, updated, extra)
        - Cost breakdown by provider and task type
        - Tool execution statistics (calls, success rates)
        - Full iteration log (last 50)
        - Recovery events
        
        Returns:
            Report dictionary ready for JSON serialization
        """
        report = {
            "session_id": self.state.session_id,
            "generated_at": datetime.now().isoformat(),
            "duration_seconds": (datetime.now() - self.state.start_time).total_seconds(),
            "total_merchants": self.state.merchants_total,
            "completed": self.state.merchants_completed,
            "failed": self.state.merchants_failed,
            "budget_exceeded": self.state.budget_exceeded,
            "summary": {
                "total_deals_audited": 0,
                "fresh": 0,
                "stale": 0,
                "missing": 0,
                "updated": 0,
                "extra": 0,
                "unknown": 0,
                "error": 0,
            },
            "cost_breakdown": {
                "total_usd": self.state.total_cost_usd,
                "by_provider": self._calculate_cost_breakdown(),
                "by_task_type": self._calculate_task_cost_breakdown(),
            },
            "tool_call_stats": self.registry.get_stats(),
            "merchants": [],
            "iterations_log": [
                {
                    "step": i.step_number,
                    "phase": i.phase.value,
                    "action": i.action,
                    "tool_called": i.tool_called,
                    "observation": i.observation,
                    "decision": i.decision,
                    "tokens": i.tokens_consumed,
                    "cost_usd": i.cost_usd,
                    "provider": i.llm_provider,
                    "wall_clock_seconds": i.wall_clock_time,
                }
                for i in self.state.iterations[-50:]  # Last 50 iterations
            ],
            "recovery_events": [
                {
                    "step": i.step_number,
                    "phase": i.phase.value,
                    "tool": i.tool_called,
                    "error": i.observation,
                    "recovery": i.decision,
                }
                for i in self.state.iterations
                if i.phase == Phase.DECIDE and i.decision != "CONTINUE"
            ],
        }

        for merchant_result in self.state.merchant_results:
            for deal in merchant_result.classified_deals:
                status = deal.status.value.lower()
                if status in report["summary"]:
                    report["summary"][status] += 1
                else:
                    report["summary"]["unknown"] += 1
                report["summary"]["total_deals_audited"] += 1

            report["merchants"].append({
                "merchant_id": merchant_result.merchant_id,
                "name": merchant_result.name,
                "url": merchant_result.url,
                "status": merchant_result.status,
                "error_message": merchant_result.error_message,
                "health_score": merchant_result.health_score,
                "db_deals_count": len(merchant_result.db_deals),
                "live_deals_count": len(merchant_result.live_deals),
                "deals": [deal.model_dump(mode="json") for deal in merchant_result.classified_deals],
                "tool_calls_used": merchant_result.tool_calls_used,
                "time_taken_seconds": merchant_result.time_taken,
                "fallback_used": merchant_result.fallback_used,
                "recovery_events": merchant_result.recovery_events,
            })
        
        return report

    def _record_planner_usage(self) -> None:
        """Record token and cost usage from the most recent planner call."""
        tokens_used = self.planner.last_tokens_used
        cost_usd = self.planner.last_cost_usd
        provider = self.planner.last_provider

        if tokens_used <= 0:
            return

        self.budget_enforcer.record_tokens(tokens_used, provider)
        self.state.total_tokens = self.budget_enforcer.tokens_used
        self.state.total_cost_usd += cost_usd
    
    def _calculate_cost_breakdown(self) -> dict:
        """
        Calculate cost breakdown by provider.
        
        Returns:
            Dictionary with cost info by provider
        """
        from llm.cost_tracker import CostTracker
        
        cost_tracker = CostTracker()
        by_provider = {}
        
        # Calculate costs for each provider based on tokens used
        for provider, tokens in self.budget_enforcer.tokens_by_provider.items():
            if provider in cost_tracker.providers:
                config = cost_tracker.providers[provider]
                # Approximate: assume 30% output, 70% input for token split
                input_tokens = int(tokens * 0.7)
                output_tokens = int(tokens * 0.3)
                input_cost = input_tokens * config.input_cost_per_million / 1_000_000
                output_cost = output_tokens * config.output_cost_per_million / 1_000_000
                
                by_provider[provider] = {
                    "tokens": tokens,
                    "cost_usd": round(input_cost + output_cost, 6),
                }
        
        return by_provider

    def _calculate_task_cost_breakdown(self) -> dict:
        """Calculate token and cost breakdown by high-level task type."""
        by_task_type = {}

        for iteration in self.state.iterations:
            if iteration.cost_usd <= 0 and iteration.tokens_consumed <= 0:
                continue

            if iteration.phase == Phase.PLAN:
                task_type = "PLANNING"
            elif iteration.tool_called == "extract_deals":
                task_type = "DEAL_EXTRACTION"
            elif iteration.tool_called == "classify_deals":
                task_type = "CLASSIFICATION"
            else:
                task_type = iteration.tool_called or iteration.phase.value

            if task_type not in by_task_type:
                by_task_type[task_type] = {
                    "tokens": 0,
                    "cost_usd": 0.0,
                }

            by_task_type[task_type]["tokens"] += iteration.tokens_consumed
            by_task_type[task_type]["cost_usd"] += iteration.cost_usd

        for task_data in by_task_type.values():
            task_data["cost_usd"] = round(task_data["cost_usd"], 6)

        return by_task_type
    
    def _save_report(self) -> None:
        """
        Save the audit report to disk as JSON.
        
        Creates reports/ directory if needed and saves with filename:
        audit_{session_id}.json
        """
        if not self.state or not self.state.final_report:
            logger.warning("No report to save")
            return
        
        # Create reports directory
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        
        # Save report to JSON file
        report_path = reports_dir / f"audit_{self.state.session_id}.json"
        report_path.write_text(json.dumps(self.state.final_report, indent=2))
        
        logger.info(f"Report saved to {report_path}")
