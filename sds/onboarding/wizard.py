# =============================================================================
# sds/onboarding/wizard.py — First-run setup wizard orchestrator
# =============================================================================
# This module drives the complete onboarding experience.
# It is invoked by the `onboard` CLI command and also auto-triggered by
# other commands when .env hasn't been populated yet.
#
# The wizard:
#   1. Checks whether setup has already been done.
#   2. Runs each step from onboarding/steps.py in sequence.
#   3. Writes all collected values to .env via sds/config.write_env().
#   4. Runs the full dependency/git/vscode setup pipeline.
#   5. Prints a completion summary.
#
# If the user cancels mid-wizard (Ctrl+C), a partial .env may have been
# written — that's fine, they can re-run `onboard` to complete it.
# =============================================================================

import sys
from typing import Optional

from rich.progress import Progress, SpinnerColumn, TextColumn

from sds.config import cfg, write_env, ENV_FILE
from sds.ui.console import (
    console,
    print_banner,
    print_header,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_rule,
)
from sds.onboarding.steps import (
    step_identity,
    step_git,
    step_streamlit,
    step_vscode_tunnel,
    step_microsoft_auth,
)


def run_wizard(force: bool = False) -> bool:
    """
    Run the full onboarding wizard.

    Args:
        force: If True, run the wizard even if .env already exists.
               Useful for re-configuring an existing installation.

    Returns:
        True if onboarding completed successfully, False if the user
        cancelled or an error occurred.
    """
    print_banner()
    print_header(
        "Onboarding Wizard",
        "Let's set up your Streamlit Development Machine.",
    )

    # --- Guard: skip if already configured ---
    if cfg.is_configured and not force:
        print_warning(
            f".env already exists at [cyan]{ENV_FILE}[/cyan]\n"
            "  Run with [bold cyan]--force[/bold cyan] to reconfigure."
        )
        confirm = _ask_proceed("Proceed with reconfiguration anyway?", default=False)
        if not confirm:
            print_info("Onboarding skipped. Existing config is intact.")
            return True

    console.print(
        "  This wizard will walk you through [bold]5 steps[/bold]:\n"
        "  1. Identity lock (one-user enforcement)\n"
        "  2. Git credentials + repository URL\n"
        "  3. Streamlit dev server settings\n"
        "  4. VSCode tunnel name\n"
        "  5. Microsoft authentication details\n"
    )

    confirm_start = _ask_proceed("Ready to begin?", default=True)
    if not confirm_start:
        print_info("Onboarding cancelled.")
        return False

    print_rule()

    # Accumulate all values collected across steps.
    all_values: dict[str, str] = {}

    # --- Run each step ---
    steps = [
        ("Identity lock",           step_identity),
        ("Git configuration",       step_git),
        ("Streamlit settings",      step_streamlit),
        ("VSCode tunnel",           step_vscode_tunnel),
        ("Microsoft auth",          step_microsoft_auth),
    ]

    for step_name, step_fn in steps:
        console.print()
        result = step_fn()

        if result is None:
            # User cancelled this step — abort the whole wizard.
            print_error(f"Step '{step_name}' was cancelled. Onboarding aborted.")
            console.print(
                "\n  [dim]Any values collected before this point have NOT been saved.\n"
                "  Run [bold cyan]python main.py onboard[/bold cyan] to start over.[/dim]"
            )
            return False

        all_values.update(result)
        print_success(f"{step_name} — done.")
        print_rule()

    # --- Write all collected values to .env ---
    console.print()
    print_info("Saving configuration to .env ...")
    write_env(all_values)
    print_success(f"Configuration saved to [cyan]{ENV_FILE}[/cyan]")

    # --- Run setup pipeline ---
    console.print()
    print_header("Running Setup", "Installing dependencies and configuring git...")
    _run_setup_pipeline()

    # --- Done ---
    console.print()
    print_success("[bold]Onboarding complete![/bold]")
    console.print(
        "\n  You can now start the development machine:\n\n"
        "    [bold cyan]python main.py start[/bold cyan]\n\n"
        "  Other useful commands:\n"
        "    [bold cyan]python main.py status[/bold cyan]     — check service status\n"
        "    [bold cyan]python main.py attach[/bold cyan]     — stream Streamlit logs\n"
        "    [bold cyan]python main.py --help[/bold cyan]     — all commands\n"
    )
    return True


# ---------------------------------------------------------------------------
# Setup pipeline — called after wizard completes
# ---------------------------------------------------------------------------

def _run_setup_pipeline() -> None:
    """
    Run the full automated setup after onboarding values are collected.

    This runs in order:
    1. Install Python packages (pip install -r requirements.txt)
    2. Install system tools (git, code CLI)
    3. Configure git (user.name, user.email, credential helper)
    4. Clone / pull the repository
    5. Write .vscode/tasks.json
    """
    # Import setup modules here to avoid import-time side effects.
    from sds.setup.deps import install_all
    from sds.setup.git_setup import setup_git
    from sds.setup.vscode_setup import write_vscode_tasks

    steps = [
        ("Installing Python packages + system tools", install_all),
        ("Configuring git and cloning repository",    setup_git),
        ("Writing VSCode tasks",                       write_vscode_tasks),
    ]

    for description, fn in steps:
        with Progress(
            SpinnerColumn(),
            TextColumn(f"[cyan]{description}...[/cyan]"),
            transient=True,
            console=console,
        ) as progress:
            progress.add_task(description, total=None)
            try:
                fn()
            except Exception as exc:
                print_error(f"{description} failed: {exc}")
                print_warning("You can retry by running [bold cyan]python main.py onboard --force[/bold cyan]")
                return

        print_success(description)


# ---------------------------------------------------------------------------
# Small helper
# ---------------------------------------------------------------------------

def _ask_proceed(message: str, default: bool) -> bool:
    """Prompt the user and return bool. Defaults to `default` on Ctrl+C."""
    from sds.ui.prompts import ask_confirm
    result = ask_confirm(message, default=default)
    return result if result is not None else False
