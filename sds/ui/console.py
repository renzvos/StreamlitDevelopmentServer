# =============================================================================
# sds/ui/console.py — Shared Rich console and display helpers
# =============================================================================
# All terminal output in this project goes through this module.
# Centralising the Console instance means styling is consistent everywhere
# and themes can be changed in one place.
#
# Usage:
#   from sds.ui.console import console, print_header, print_success, ...
# =============================================================================

from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

# ---------------------------------------------------------------------------
# Shared console instance
# ---------------------------------------------------------------------------
# Every module that produces output should import THIS console object rather
# than creating its own. Using a single instance prevents interleaved output
# when Rich's live-render features are in use.
console = Console()


# ---------------------------------------------------------------------------
# App header / banner
# ---------------------------------------------------------------------------

def print_banner() -> None:
    """Print the application banner. Called once at startup."""
    banner = Text()
    banner.append("  Streamlit Development Machine  \n", style="bold white on blue")
    banner.append("  Automated Dev Environment CLI  ", style="dim white on blue")
    console.print(Panel(banner, border_style="blue", padding=(0, 2)))
    console.print()


def print_header(text: str, subtitle: str = "") -> None:
    """
    Print a prominent section header.

    Args:
        text: Main heading text.
        subtitle: Optional secondary line shown below the heading.
    """
    header = Text(text, style="bold cyan")
    if subtitle:
        header.append(f"\n{subtitle}", style="dim")
    console.print(Panel(header, border_style="cyan", padding=(0, 1)))


# ---------------------------------------------------------------------------
# Status messages
# ---------------------------------------------------------------------------

def print_success(message: str) -> None:
    """Print a green success message with a checkmark."""
    console.print(f"[bold green]✓[/bold green] {message}")


def print_error(message: str) -> None:
    """Print a red error message with a cross."""
    console.print(f"[bold red]✗[/bold red] {message}")


def print_warning(message: str) -> None:
    """Print a yellow warning message with an exclamation."""
    console.print(f"[bold yellow]![/bold yellow] {message}")


def print_info(message: str) -> None:
    """Print a blue informational message."""
    console.print(f"[bold blue]→[/bold blue] {message}")


def print_step(step_num: int, total: int, description: str) -> None:
    """
    Print a numbered step indicator.

    Example output:  [2/5] Configuring git...
    """
    console.print(f"[bold white][[cyan]{step_num}[/cyan]/[cyan]{total}[/cyan]][/bold white] {description}")


# ---------------------------------------------------------------------------
# Status dashboard table
# ---------------------------------------------------------------------------

def print_status_table(services: list[dict]) -> None:
    """
    Print a formatted table showing the status of all services.

    Args:
        services: List of dicts with keys:
            - name (str): Service name
            - status (str): "running" | "stopped" | "error" | "unknown"
            - detail (str): Optional extra info (PID, URL, etc.)
    """
    table = Table(
        title="Service Status",
        box=box.ROUNDED,
        border_style="cyan",
        show_header=True,
        header_style="bold cyan",
        padding=(0, 1),
    )
    table.add_column("Service", style="bold white", min_width=20)
    table.add_column("Status", min_width=12)
    table.add_column("Details", style="dim")

    # Map status strings to coloured labels.
    STATUS_STYLES = {
        "running": "[bold green]● running[/bold green]",
        "stopped": "[bold red]○ stopped[/bold red]",
        "error":   "[bold red]✗ error[/bold red]",
        "unknown": "[dim]? unknown[/dim]",
    }

    for svc in services:
        name = svc.get("name", "")
        raw_status = svc.get("status", "unknown")
        detail = svc.get("detail", "")
        status_label = STATUS_STYLES.get(raw_status, f"[dim]{raw_status}[/dim]")
        table.add_row(name, status_label, detail)

    console.print()
    console.print(table)
    console.print(
        f"[dim]  Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
    )
    console.print()


# ---------------------------------------------------------------------------
# Rule / divider
# ---------------------------------------------------------------------------

def print_rule(title: str = "") -> None:
    """Print a horizontal rule, optionally with a centred title."""
    console.rule(title, style="dim")


# ---------------------------------------------------------------------------
# Compact key-value pair display
# ---------------------------------------------------------------------------

def print_kv(key: str, value: str) -> None:
    """Print a single key: value line, useful for config summaries."""
    console.print(f"  [bold]{key}:[/bold] [cyan]{value}[/cyan]")


def print_config_summary(config_dict: dict) -> None:
    """
    Print a panel showing all config key/value pairs.

    Sensitive values (tokens, passwords) are masked automatically.
    """
    SENSITIVE_KEYWORDS = ("token", "password", "secret", "fingerprint")

    lines = []
    for key, value in config_dict.items():
        display_value = value
        if any(kw in key.lower() for kw in SENSITIVE_KEYWORDS):
            # Mask all but first 4 chars
            display_value = (str(value)[:4] + "****") if value else "(not set)"
        elif not value:
            display_value = "[dim](not set)[/dim]"
        lines.append(f"  [bold]{key}:[/bold] {display_value}")

    content = "\n".join(lines) if lines else "  [dim](no config)[/dim]"
    console.print(Panel(content, title="Configuration", border_style="dim", padding=(0, 1)))
