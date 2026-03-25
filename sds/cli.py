# =============================================================================
# sds/cli.py — Typer CLI application (command dispatch layer)
# =============================================================================
# This module defines all CLI commands. It is purely a dispatch layer:
# each command function validates guards and then delegates to the
# appropriate manager module. No business logic lives here.
#
# Commands:
#   onboard          First-run setup wizard
#   start            Start tunnel + Streamlit
#   stop             Stop tunnel + Streamlit
#   status           Show status table of all services
#   attach           Stream live Streamlit logs
#   tunnel start     Start VSCode tunnel only
#   tunnel stop      Stop VSCode tunnel only
#   tunnel login     Authenticate VSCode tunnel with Microsoft
#   streamlit start  Start Streamlit only
#   streamlit stop   Stop Streamlit only
#   streamlit restart Restart Streamlit
# =============================================================================

from typing import Optional, Annotated

import typer
from rich.console import Console

# Sub-apps for command groups.
app = typer.Typer(
    name="sds",
    help="Streamlit Development Machine — automated dev environment CLI.",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
)

tunnel_app  = typer.Typer(help="Manage the VSCode tunnel.", no_args_is_help=True)
stream_app  = typer.Typer(help="Manage the Streamlit dev server.", no_args_is_help=True)

# Register sub-apps as command groups.
app.add_typer(tunnel_app,  name="tunnel")
app.add_typer(stream_app,  name="streamlit")

console = Console()


# ---------------------------------------------------------------------------
# Guard helper — verify identity before any action
# ---------------------------------------------------------------------------

def _guard(docker_mode: bool = False) -> bool:
    """
    Run the identity check. Print a warning if it fails.
    Returns True if OK to proceed.
    """
    from sds.identity import identity_guard
    from sds.config import cfg
    return identity_guard(docker_mode=docker_mode or cfg.docker_mode)


# ---------------------------------------------------------------------------
# onboard — first-run wizard
# ---------------------------------------------------------------------------

@app.command()
def onboard(
    force: Annotated[bool, typer.Option(
        "--force", "-f",
        help="Re-run wizard even if .env already exists.",
    )] = False,
):
    """
    Run the onboarding wizard to configure this machine.

    This is the first command you should run on a new machine.
    It collects git credentials, Streamlit settings, VSCode tunnel name,
    and Microsoft auth details, then installs all dependencies.
    """
    from sds.onboarding.wizard import run_wizard
    success = run_wizard(force=force)
    raise typer.Exit(0 if success else 1)


# ---------------------------------------------------------------------------
# start — start everything
# ---------------------------------------------------------------------------

@app.command()
def start(
    skip_pull: Annotated[bool, typer.Option(
        "--skip-pull",
        help="Skip git pull before starting (use existing local state).",
    )] = False,
    skip_tunnel: Annotated[bool, typer.Option(
        "--skip-tunnel",
        help="Don't start the VSCode tunnel (Streamlit only).",
    )] = False,
):
    """
    Start the full development machine: VSCode tunnel + Streamlit.

    Workflow:
    1. Verify identity lock.
    2. Check/install dependencies.
    3. Git pull the latest repo changes (unless --skip-pull).
    4. Authenticate with Microsoft (device flow if needed).
    5. Start VSCode tunnel.
    6. Start Streamlit dev server.
    """
    from sds.ui.console import print_banner, print_header, print_success, print_error
    from sds.config import cfg

    print_banner()

    # Identity check.
    if not _guard():
        raise typer.Exit(1)

    print_header("Starting Dev Machine", f"Tunnel: {cfg.vscode_tunnel_name} | Streamlit: {cfg.streamlit_dev_file}")

    # --- 1. Dependency pre-flight ---
    _run_step("Checking dependencies", _check_deps)

    # --- 2. Git pull ---
    if not skip_pull:
        _run_step("Pulling latest repo changes", _git_pull)

    # --- 3. Microsoft auth ---
    _run_step("Microsoft authentication", _ensure_ms_auth)

    # --- 4. VSCode tunnel ---
    if not skip_tunnel:
        _run_step("Starting VSCode tunnel", _start_tunnel)

    # --- 5. Streamlit ---
    _run_step("Starting Streamlit dev server", _start_streamlit)

    # --- Summary ---
    _print_status_summary()


# ---------------------------------------------------------------------------
# stop — stop everything
# ---------------------------------------------------------------------------

@app.command()
def stop(
    skip_tunnel: Annotated[bool, typer.Option(
        "--skip-tunnel",
        help="Don't stop the VSCode tunnel.",
    )] = False,
):
    """
    Stop the Streamlit dev server and VSCode tunnel.
    """
    if not _guard():
        raise typer.Exit(1)

    from sds.ui.console import print_header
    print_header("Stopping Dev Machine")

    from sds import streamlit as st_module
    from sds.streamlit.daemon import stop as st_stop
    from sds.tunnel.manager import stop as tunnel_stop

    ok = st_stop()
    if not skip_tunnel:
        ok = tunnel_stop() and ok

    raise typer.Exit(0 if ok else 1)


# ---------------------------------------------------------------------------
# status — show live status table
# ---------------------------------------------------------------------------

@app.command()
def status():
    """
    Show the current status of all managed services.
    """
    if not _guard():
        raise typer.Exit(1)

    from sds.streamlit.daemon import status as st_status
    from sds.tunnel.manager import status as tunnel_status
    from sds.auth.microsoft import is_authenticated
    from sds.ui.console import print_banner, print_status_table, print_kv
    from sds.config import cfg

    print_banner()

    st  = st_status()
    tn  = tunnel_status()
    ms  = is_authenticated()

    # Build rows for the status table.
    services = [
        {
            "name": "Streamlit Dev Server",
            "status": "running" if st["running"] else "stopped",
            "detail": (
                f"PID {st['pid']} | {st['url']}"
                if st["running"]
                else f"file: {st['entry_file']}"
            ),
        },
        {
            "name": "VSCode Tunnel",
            "status": "running" if tn["running"] else "stopped",
            "detail": (
                f"PID {tn['pid']} | {tn['url']}"
                if tn["running"]
                else f"name: {tn['tunnel_name']}"
            ),
        },
        {
            "name": "Microsoft Auth",
            "status": "running" if ms else "stopped",
            "detail": "token valid" if ms else "not authenticated",
        },
    ]

    print_status_table(services)

    # Print uptime if Streamlit is running.
    if st["running"] and st.get("uptime_seconds"):
        uptime = int(st["uptime_seconds"])
        h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60
        print_kv("Streamlit uptime", f"{h:02d}:{m:02d}:{s:02d}")


# ---------------------------------------------------------------------------
# attach — stream live Streamlit logs
# ---------------------------------------------------------------------------

@app.command()
def attach():
    """
    Attach to the running Streamlit process and stream its live output.

    This connects to the IPC socket and streams stdout/stderr from the
    Streamlit process to this terminal in real time.
    Press Ctrl+C to detach (Streamlit keeps running).
    """
    if not _guard():
        raise typer.Exit(1)

    from sds.streamlit.ipc import IPCClient
    client = IPCClient()
    client.attach()


# ---------------------------------------------------------------------------
# tunnel sub-commands
# ---------------------------------------------------------------------------

@tunnel_app.command("start")
def tunnel_start():
    """Start the VSCode tunnel."""
    if not _guard():
        raise typer.Exit(1)
    from sds.tunnel.manager import start
    ok = start()
    raise typer.Exit(0 if ok else 1)


@tunnel_app.command("stop")
def tunnel_stop():
    """Stop the VSCode tunnel."""
    if not _guard():
        raise typer.Exit(1)
    from sds.tunnel.manager import stop
    ok = stop()
    raise typer.Exit(0 if ok else 1)


@tunnel_app.command("login")
def tunnel_login():
    """
    Authenticate the VSCode tunnel with a Microsoft account.

    Runs `code tunnel user login --provider microsoft` interactively.
    You will see a device code prompt in this terminal.
    """
    if not _guard():
        raise typer.Exit(1)
    from sds.tunnel.manager import login
    ok = login()
    raise typer.Exit(0 if ok else 1)


@tunnel_app.command("status")
def tunnel_status_cmd():
    """Show VSCode tunnel status."""
    if not _guard():
        raise typer.Exit(1)
    from sds.tunnel.manager import status
    from sds.ui.console import print_status_table
    tn = status()
    print_status_table([{
        "name": "VSCode Tunnel",
        "status": "running" if tn["running"] else "stopped",
        "detail": tn.get("url") or tn["tunnel_name"],
    }])


# ---------------------------------------------------------------------------
# streamlit sub-commands
# ---------------------------------------------------------------------------

@stream_app.command("start")
def streamlit_start():
    """Start the Streamlit dev server."""
    if not _guard():
        raise typer.Exit(1)
    from sds.streamlit.daemon import start
    ok = start()
    raise typer.Exit(0 if ok else 1)


@stream_app.command("stop")
def streamlit_stop():
    """Stop the Streamlit dev server."""
    if not _guard():
        raise typer.Exit(1)
    from sds.streamlit.daemon import stop
    ok = stop()
    raise typer.Exit(0 if ok else 1)


@stream_app.command("restart")
def streamlit_restart():
    """Restart the Streamlit dev server (stop + start)."""
    if not _guard():
        raise typer.Exit(1)
    from sds.streamlit.daemon import restart
    ok = restart()
    raise typer.Exit(0 if ok else 1)


@stream_app.command("status")
def streamlit_status_cmd():
    """Show Streamlit dev server status."""
    if not _guard():
        raise typer.Exit(1)
    from sds.streamlit.daemon import status
    from sds.ui.console import print_status_table
    st = status()
    print_status_table([{
        "name": "Streamlit Dev Server",
        "status": "running" if st["running"] else "stopped",
        "detail": st.get("url") or st["entry_file"],
    }])


# ---------------------------------------------------------------------------
# Internal step helpers (used by `start` command)
# ---------------------------------------------------------------------------

def _run_step(label: str, fn) -> None:
    """
    Run a setup step. On failure, print the error and exit.
    This keeps the `start` command readable.
    """
    from sds.ui.console import print_info, print_error
    try:
        fn()
    except Exception as exc:
        print_error(f"{label} failed: {exc}")
        raise typer.Exit(1) from exc


def _check_deps() -> None:
    """Pre-flight: ensure pip packages and system tools are available."""
    from sds.setup.deps import install_all
    install_all()


def _git_pull() -> None:
    """Pull the latest changes from the configured repo."""
    from sds.setup.git_setup import clone_or_pull
    clone_or_pull()


def _ensure_ms_auth() -> None:
    """Ensure Microsoft auth tokens are valid (interactive if needed)."""
    from sds.auth.microsoft import ensure_authenticated
    ensure_authenticated()


def _start_tunnel() -> None:
    """Start VSCode tunnel; raise on failure."""
    from sds.tunnel.manager import start
    if not start():
        raise RuntimeError("VSCode tunnel failed to start.")


def _start_streamlit() -> None:
    """Start Streamlit; raise on failure."""
    from sds.streamlit.daemon import start
    if not start():
        raise RuntimeError("Streamlit dev server failed to start.")


def _print_status_summary() -> None:
    """Print a compact status table after a successful start."""
    from sds.streamlit.daemon import status as st_status
    from sds.tunnel.manager import status as tunnel_status
    from sds.auth.microsoft import is_authenticated
    from sds.ui.console import print_status_table

    st = st_status()
    tn = tunnel_status()

    print_status_table([
        {
            "name": "Streamlit Dev Server",
            "status": "running" if st["running"] else "stopped",
            "detail": st.get("url", ""),
        },
        {
            "name": "VSCode Tunnel",
            "status": "running" if tn["running"] else "stopped",
            "detail": tn.get("url", ""),
        },
    ])
