"""
Rich terminal UI for live agent execution display.

Displays real-time updates of agent progress with:
- Session info and timing
- Merchant progress
- Token and tool call usage
- Recent iteration log
- Current phase and decision
"""

import logging
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn
from rich.table import Table
from rich.text import Text

from agent.state import AgentState, AgentIteration

logger = logging.getLogger(__name__)


class TerminalUI:
    """
    Rich terminal dashboard for live agent updates.
    
    Shows real-time progress, token usage, tool calls,
    and recent iteration log.
    """
    
    def __init__(self):
        """Initialize terminal UI."""
        self.console = Console()
        self.live: Optional[Live] = None
        self.layout: Optional[Layout] = None
        self.state: Optional[AgentState] = None
    
    def live_context(self):
        """Context manager for live rendering."""
        return self
    
    def __enter__(self):
        """Enter live context."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit live context and clean up."""
        if self.live:
            self.live.stop()
            self.live = None
    
    def update(self, state: AgentState) -> None:
        """
        Update UI with current agent state.
        
        Args:
            state: Current AgentState
        """
        self.state = state
        
        if not self.live:
            # First update - start live rendering
            self.live = Live(self._render_layout(), refresh_per_second=2, console=self.console)
            self.live.start()
        
        # Update layout content
        if self.live:
            self.live.update(self._render_layout())
    
    def _render_layout(self) -> Layout:
        """Render the complete dashboard layout."""
        layout = Layout()
        
        # Header
        layout.split(
            Layout(self._render_header(), size=3),
            Layout(
                name="body"
            )
        )
        
        # Body: split into progress panels and details
        body_layout = layout["body"]
        body_layout.split_row(
            Layout(self._render_merchant_progress(), name="merchants"),
            Layout(self._render_metrics(), name="metrics"),
        )
        
        # Add iteration log at bottom
        layout.split(
            Layout(self._render_header(), size=3),
            Layout(self._render_merchant_progress(), name="merchants", size=10),
            Layout(self._render_metrics(), name="metrics", size=8),
            Layout(self._render_iterations(), name="iterations", size=6),
        )
        
        return layout
    
    def _render_header(self) -> Panel:
        """Render header with session info."""
        if not self.state:
            return Panel("[*] GrabOn Deal Audit Agent — Initializing...", style="bold blue")
        
        start_time = self.state.start_time.strftime("%H:%M:%S") if self.state.start_time else "N/A"
        elapsed = (datetime.utcnow() - self.state.start_time).total_seconds() if self.state.start_time else 0
        
        current = f" | Currently: {self.state.current_merchant}" if self.state.current_merchant else ""
        
        header_text = (
            f"[*] GrabOn Deal Audit Agent — LIVE\n"
            f"Session: {self.state.session_id[:8]}  |  "
            f"Started: {start_time}  |  "
            f"Elapsed: {int(elapsed)}s{current}"
        )
        
        return Panel(header_text, style="bold cyan")
    
    def _render_merchant_progress(self) -> Panel:
        """Render merchant progress table."""
        if not self.state:
            return Panel("No data", style="dim")
        
        table = Table(title="Merchant Progress", show_header=True)
        table.add_column("Status", style="cyan", width=3)
        table.add_column("Merchant", width=15)
        table.add_column("Result", width=12)
        
        # Add completed merchants
        for result in self.state.merchant_results:
            icon = "[OK]"
            if result.status == "failed":
                icon = "[X]"
            elif result.status == "pending":
                icon = "[...]"
            elif result.status == "error":
                icon = "[!]"
            
            result_text = (
                f"{result.status[:8]}"
                if result.status
                else "pending"
            )
            
            table.add_row(icon, result.name[:15], result_text)
        
        # Add current merchant if not in results
        if self.state.current_merchant:
            current = next(
                (r for r in self.state.merchant_results if r.merchant_id == self.state.current_merchant),
                None
            )
            if not current:
                table.add_row("[>]", self.state.current_merchant[:15], "in-progress")
        
        # Add pending slots
        pending_count = self.state.merchants_total - len(self.state.merchant_results)
        for i in range(min(pending_count, 3)):  # Show up to 3 pending
            table.add_row("[...]", f"(pending #{i+1})", "")
        
        return Panel(table, style="green")
    
    def _render_metrics(self) -> Panel:
        """Render token and call metrics."""
        if not self.state:
            return Panel("No data", style="dim")
        
        # Token progress bar
        token_pct = (self.state.total_tokens / 150000 * 100) if self.state.total_tokens else 0
        token_text = f"Tokens: {self.state.total_tokens:,}/150,000 ({token_pct:.0f}%)"
        
        # Tool calls progress bar
        calls_pct = (self.state.total_tool_calls / 200 * 100) if self.state.total_tool_calls else 0
        calls_text = f"Tool Calls: {self.state.total_tool_calls}/200 ({calls_pct:.0f}%)"
        
        # Cost
        cost_text = f"💰 Cost: ${self.state.total_cost_usd:.6f}"
        
        # Failures
        failures_text = f"Failures: {self.state.consecutive_failures}"
        
        metrics_content = (
            f"{token_text}\n"
            f"█{'█' * int(token_pct / 5)}░{'░' * (20 - int(token_pct / 5))}\n\n"
            f"{calls_text}\n"
            f"█{'█' * int(calls_pct / 5)}░{'░' * (20 - int(calls_pct / 5))}\n\n"
            f"{cost_text}\n"
            f"{failures_text}"
        )
        
        return Panel(metrics_content, style="yellow")
    
    def _render_iterations(self) -> Panel:
        """Render recent iterations log."""
        if not self.state or not self.state.iterations:
            return Panel("(No iterations yet)", style="dim")
        
        # Show last 5 iterations
        recent = self.state.iterations[-5:]
        
        lines = []
        for it in recent:
            phase_color = {
                "PLAN": "cyan",
                "ACT": "yellow",
                "OBSERVE": "blue",
                "DECIDE": "green",
            }.get(it.phase.value, "white")
            
            tool_str = f" | {it.tool_called}" if it.tool_called else ""
            line = (
                f"[{phase_color}]Step {it.step_number} | {it.phase.value}{tool_str}[/{phase_color}] "
                f"→ {it.decision[:40]}"
            )
            lines.append(line)
        
        content = "\n".join(lines)
        
        return Panel(content, title="Recent Iterations", style="magenta")
    
    def print_summary(self, state: AgentState) -> None:
        """
        Print final summary after execution.
        
        Args:
            state: Final agent state
        """
        self.console.print("\n" + "="*70, style="bold")
        self.console.print("[*] AUDIT COMPLETE", style="bold green")
        self.console.print("="*70 + "\n")
        
        # Summary stats
        summary_table = Table(title="Execution Summary")
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Value", style="green")
        
        summary_table.add_row(
            "Total Merchants",
            f"{state.merchants_total}"
        )
        summary_table.add_row(
            "Completed",
            f"{state.merchants_completed} [OK]"
        )
        summary_table.add_row(
            "Failed",
            f"{state.merchants_failed} [X]"
        )
        summary_table.add_row(
            "Total Tokens",
            f"{state.total_tokens:,}"
        )
        summary_table.add_row(
            "Total Cost",
            f"${state.total_cost_usd:.6f}"
        )
        summary_table.add_row(
            "Tool Calls",
            f"{state.total_tool_calls}"
        )
        summary_table.add_row(
            "Execution Time",
            f"{(datetime.utcnow() - state.start_time).total_seconds():.1f}s"
        )
        
        self.console.print(summary_table)
        self.console.print()
    
    def print_error(self, message: str) -> None:
        """
        Print error message.
        
        Args:
            message: Error message
        """
        self.console.print(f"[bold red][X] ERROR:[/bold red] {message}")
    
    def print_info(self, message: str) -> None:
        """
        Print info message.
        
        Args:
            message: Info message
        """
        self.console.print(f"[bold cyan]ℹ️  INFO:[/bold cyan] {message}")
