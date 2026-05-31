"""
GrabOn Merchant Deal Audit Agent — Entry Point

Main execution script for the autonomous deal audit agent.

Usage:
    python main.py                    # Run full audit (all 20 merchants)
    python main.py --merchants 5      # Run first 5 merchants only
    python main.py --eval             # Run eval suite instead
    python main.py --merchant amazon  # Run single merchant by ID

Environment:
    - Copy .env.example to .env and fill in your API keys
    - LANGCHAIN_TRACING_V2=true for LangSmith integration
    - See .env.example for all configuration options

Exit codes:
    0: Success
    1: General error
    2: Budget exceeded
    3: No merchants to audit
"""

import asyncio
import argparse
import json
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv

# Configure logging before imports
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

from agent.loop import AgentLoop
from agent.budget import BudgetExceededError
from observability.terminal_ui import TerminalUI


def load_merchants(limit: int = None, merchant_id: str = None) -> list:
    """
    Load merchants from data/merchants.json.
    
    Args:
        limit: Maximum number of merchants to load (None = all)
        merchant_id: Specific merchant ID to load (overrides limit)
        
    Returns:
        List of merchant dicts with 'id', 'name', 'url' keys
        
    Raises:
        FileNotFoundError: If merchants.json not found
        ValueError: If no merchants loaded
    """
    merchants_path = Path("data/merchants.json")
    
    if not merchants_path.exists():
        logger.error(f"Merchants file not found: {merchants_path}")
        raise FileNotFoundError(f"Missing {merchants_path}")
    
    try:
        merchants = json.loads(merchants_path.read_text())
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in merchants.json: {e}")
        raise ValueError(f"Merchants JSON parse error: {e}")
    
    if not merchants:
        logger.error("No merchants found in merchants.json")
        raise ValueError("Empty merchants list")
    
    # Filter by specific ID if requested
    if merchant_id:
        filtered = [m for m in merchants if m.get("id") == merchant_id]
        if not filtered:
            logger.error(f"Merchant not found: {merchant_id}")
            raise ValueError(f"Merchant '{merchant_id}' not found")
        merchants = filtered
        logger.info(f"Loaded 1 merchant: {merchant_id}")
    elif limit:
        merchants = merchants[:limit]
        logger.info(f"Loaded {len(merchants)} merchants (limited to {limit})")
    else:
        logger.info(f"Loaded all {len(merchants)} merchants")
    
    return merchants


async def run_audit(merchants: list) -> int:
    """
    Run the main audit loop.
    
    Args:
        merchants: List of merchants to audit
        
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    if not merchants:
        logger.error("No merchants to audit")
        return 3
    
    try:
        # Create UI for live updates
        ui = TerminalUI()
        
        # Create and run agent loop
        agent = AgentLoop(ui=ui)
        
        logger.info(f"Starting audit for {len(merchants)} merchants")
        
        # Run with live UI context
        with ui.live_context():
            state = await agent.run(merchants)
        
        # Report results
        print("\n" + "=" * 70)
        print("✅ AUDIT COMPLETE")
        print("=" * 70)
        print(f"Session ID:        {state.session_id}")
        print(f"Merchants:         {state.merchants_completed} completed, {state.merchants_failed} failed")
        print(f"Total tokens:      {state.total_tokens:,}")
        print(f"Total cost:        ${state.total_cost_usd:.4f}")
        print(f"Budget exceeded:   {'YES' if state.budget_exceeded else 'NO'}")
        
        if state.final_report:
            summary = state.final_report.get("summary", {})
            print(f"\nDeal Summary:")
            print(f"  Fresh:      {summary.get('fresh', 0)}")
            print(f"  Stale:      {summary.get('stale', 0)}")
            print(f"  Missing:    {summary.get('missing', 0)}")
            print(f"  Updated:    {summary.get('updated', 0)}")
            print(f"  Extra:      {summary.get('extra', 0)}")
        
        # Check exit condition
        if state.budget_exceeded:
            logger.warning("Audit halted due to budget exceeded")
            return 2
        
        return 0
    
    except BudgetExceededError as e:
        logger.error(f"Budget enforcement error: {e}")
        print(f"\n[X] BUDGET EXCEEDED: {e}")
        return 2
    except Exception as e:
        logger.error(f"Audit error: {e}", exc_info=True)
        print(f"\n[X] AUDIT ERROR: {e}")
        return 1


async def run_evals() -> int:
    """
    Run the evaluation suite instead of main audit.
    
    Returns:
        Exit code (0 for all tests passed, 1 for failures)
    """
    try:
        from evals.runner import EvalRunner
        
        logger.info("Starting eval suite")
        
        runner = EvalRunner()
        results = await runner.run_all()
        
        # Print summary
        print("\n" + "=" * 70)
        print("📊 EVAL SUITE RESULTS")
        print("=" * 70)
        
        runner.print_summary(results)
        
        # Check if all passed
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        
        if passed == total:
            print(f"\n✅ All {total} evals passed!")
            return 0
        else:
            print(f"\n⚠️  {passed}/{total} evals passed")
            return 1
    
    except ImportError:
        logger.error("Eval runner not yet implemented")
        print("❌ Eval runner not yet implemented")
        return 1
    except Exception as e:
        logger.error(f"Eval error: {e}", exc_info=True)
        print(f"❌ EVAL ERROR: {e}")
        return 1


def main():
    """
    Parse arguments and dispatch to appropriate handler.
    """
    parser = argparse.ArgumentParser(
        description="GrabOn Merchant Deal Audit Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    Run full audit (all merchants)
  %(prog)s --merchants 5      Audit first 5 merchants
  %(prog)s --merchant amazon  Audit only Amazon
  %(prog)s --eval             Run evaluation suite
        """,
    )
    
    parser.add_argument(
        "--merchants",
        type=int,
        default=None,
        help="Limit to first N merchants (default: all)",
    )
    
    parser.add_argument(
        "--merchant",
        type=str,
        default=None,
        help="Audit specific merchant by ID",
    )
    
    parser.add_argument(
        "--eval",
        action="store_true",
        help="Run evaluation suite instead of audit",
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )
    
    args = parser.parse_args()
    
    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    # Dispatch handler
    try:
        if args.eval:
            # Run eval suite
            exit_code = asyncio.run(run_evals())
        else:
            # Load merchants and run audit
            merchants = load_merchants(
                limit=args.merchants,
                merchant_id=args.merchant,
            )
            exit_code = asyncio.run(run_audit(merchants))
        
        sys.exit(exit_code)
    
    except KeyboardInterrupt:
        print("\n\n[!] Interrupted by user")
        sys.exit(1)
    
    except (FileNotFoundError, ValueError) as e:
        print(f"[X] Configuration error: {e}")
        sys.exit(1)
    
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"[X] FATAL ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
