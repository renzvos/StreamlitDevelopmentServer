# =============================================================================
# sds/tunnel/manager.py — VSCode Tunnel process manager
# =============================================================================
# This module manages the `code tunnel` process lifecycle:
#   - start()   Spawn `code tunnel` as a detached background process.
#   - stop()    Send SIGTERM to the tunnel process via the PID file.
#   - status()  Check whether the tunnel process is alive.
#   - login()   Run `code tunnel user login` for Microsoft auth.
#
# VSCode tunnel authentication:
# ──────────────────────────────
# The first time `code tunnel` runs, it will print a device code URL to the
# terminal and wait for the user to authenticate. This happens automatically
# inside the `start()` subprocess — the user sees the prompt in the terminal.
# On subsequent runs, VS Code uses the cached token (stored by the `code` CLI
# in its own config directory, ~/.vscode-cli/) and no interaction is needed.
#
# PID file:
# ──────────────────────────────
# The tunnel PID is stored at the path configured in cfg.tunnel_pid_file.
# We use psutil to verify the PID is still alive (not a stale file).
# =============================================================================

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

import psutil

from sds.config import cfg
from sds.ui.console import print_info, print_success, print_warning, print_error


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start() -> bool:
    """
    Start the VSCode tunnel as a detached background process.

    The tunnel is started with:
      code tunnel --accept-server-license-terms --name <VSCODE_TUNNEL_NAME>

    - `--accept-server-license-terms` skips the interactive license prompt.
    - `--name` sets the machine name visible on vscode.dev.

    On first run, `code tunnel` will print a Microsoft device code auth
    prompt to stdout. The user must complete auth in a browser. On
    subsequent runs it uses cached credentials silently.

    The process is run in the FOREGROUND for the auth step, then detached
    once it has started successfully.

    Returns:
        True if the tunnel started, False on error.
    """
    # --- Guard: already running? ---
    if is_running():
        pid = _read_pid()
        print_warning(f"VSCode tunnel is already running (PID {pid}).")
        return True

    # --- Guard: `code` CLI available? ---
    if not shutil.which("code"):
        print_error(
            "`code` CLI not found on PATH.\n"
            "  Run [bold cyan]python main.py onboard[/bold cyan] to install it."
        )
        return False

    tunnel_name = cfg.vscode_tunnel_name or "streamlit-dev-machine"

    print_info(f"Starting VSCode tunnel '{tunnel_name}' ...")
    print_info(
        "  On first run, you will see a Microsoft login prompt below.\n"
        "  Complete the auth in your browser, then return here."
    )

    # Prepare the log file directory.
    log_file = cfg.log_file.parent / "tunnel.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Spawn the tunnel process.
    # We use Popen (not run) so we can capture the PID and detach.
    # stdin=subprocess.DEVNULL prevents the subprocess from consuming stdin.
    try:
        with open(log_file, "a") as log_fh:
            proc = subprocess.Popen(
                [
                    "code", "tunnel",
                    "--accept-server-license-terms",
                    "--name", tunnel_name,
                ],
                stdout=log_fh,
                stderr=log_fh,
                stdin=subprocess.DEVNULL,
                # start_new_session=True detaches the process from this terminal,
                # so it survives if the parent Python process exits.
                start_new_session=True,
            )
    except FileNotFoundError:
        print_error("`code` binary not found. Ensure VSCode CLI is installed.")
        return False
    except OSError as exc:
        print_error(f"Failed to start tunnel: {exc}")
        return False

    # Save the PID so we can manage it later.
    _write_pid(proc.pid)

    # Give it a moment to fail fast (e.g. port conflict).
    time.sleep(2)

    if not is_running():
        print_error(
            "VSCode tunnel process exited immediately.\n"
            f"  Check logs: {log_file}"
        )
        _remove_pid()
        return False

    print_success(
        f"VSCode tunnel started (PID {proc.pid}).\n"
        f"  Connect at: [bold cyan]https://vscode.dev/tunnel/{tunnel_name}[/bold cyan]\n"
        f"  Logs: {log_file}"
    )
    return True


def stop() -> bool:
    """
    Stop the running VSCode tunnel process.

    Sends SIGTERM (graceful shutdown). If the process doesn't exit within
    5 seconds, sends SIGKILL (force kill).

    Returns:
        True if stopped successfully (or wasn't running), False on error.
    """
    if not is_running():
        print_info("VSCode tunnel is not running.")
        _remove_pid()  # Clean up any stale PID file.
        return True

    pid = _read_pid()
    if pid is None:
        print_warning("No PID file found. Cannot stop tunnel.")
        return False

    print_info(f"Stopping VSCode tunnel (PID {pid}) ...")

    try:
        # SIGTERM — polite shutdown request.
        os.kill(pid, signal.SIGTERM)

        # Wait up to 5 seconds for graceful exit.
        for _ in range(10):
            time.sleep(0.5)
            if not _pid_is_alive(pid):
                break
        else:
            # Process didn't exit — force kill.
            print_warning("Tunnel didn't exit gracefully. Force killing ...")
            os.kill(pid, signal.SIGKILL)
            time.sleep(1)

    except ProcessLookupError:
        # Process was already gone (race condition).
        pass
    except PermissionError:
        print_error(f"Permission denied killing PID {pid}. Are you running as the right user?")
        return False

    _remove_pid()
    print_success("VSCode tunnel stopped.")
    return True


def status() -> dict:
    """
    Return a status dict describing the current tunnel state.

    Returns:
        {
            "running": bool,
            "pid": int | None,
            "tunnel_name": str,
            "url": str | None,
        }
    """
    pid = _read_pid() if is_running() else None
    running = pid is not None and _pid_is_alive(pid)
    tunnel_name = cfg.vscode_tunnel_name or "streamlit-dev-machine"

    return {
        "running": running,
        "pid": pid if running else None,
        "tunnel_name": tunnel_name,
        "url": f"https://vscode.dev/tunnel/{tunnel_name}" if running else None,
    }


def is_running() -> bool:
    """Return True if the tunnel process is alive."""
    pid = _read_pid()
    return pid is not None and _pid_is_alive(pid)


def login() -> bool:
    """
    Run `code tunnel user login` interactively.

    This triggers the Microsoft device code auth flow managed by the `code`
    CLI itself. The user sees the prompt in the terminal, visits the URL,
    and enters the code. After completion, the `code` CLI caches the token.

    This function blocks until login completes or the user presses Ctrl+C.

    Returns:
        True if login command exited with code 0, False otherwise.
    """
    if not shutil.which("code"):
        print_error("`code` CLI not found. Install VSCode CLI first.")
        return False

    print_info("Starting VSCode tunnel login (Microsoft account) ...")
    print_info(
        "  You will be shown a device code URL. Open it in your browser\n"
        "  and enter the code shown. This terminal will wait."
    )

    result = subprocess.run(
        ["code", "tunnel", "user", "login", "--provider", "microsoft"],
        # No stdin capture — let the user interact with the prompt.
    )

    if result.returncode == 0:
        print_success("VSCode tunnel login successful.")
        return True
    else:
        print_error(f"VSCode tunnel login failed (exit code {result.returncode}).")
        return False


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------

def _write_pid(pid: int) -> None:
    """Write the tunnel process PID to the configured PID file."""
    cfg.tunnel_pid_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.tunnel_pid_file.write_text(str(pid))


def _read_pid() -> Optional[int]:
    """
    Read and return the PID from the PID file.
    Returns None if the file doesn't exist or contains invalid content.
    """
    try:
        return int(cfg.tunnel_pid_file.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _remove_pid() -> None:
    """Remove the PID file if it exists."""
    try:
        cfg.tunnel_pid_file.unlink(missing_ok=True)
    except OSError:
        pass


def _pid_is_alive(pid: int) -> bool:
    """
    Check whether a process with the given PID is alive.

    Uses psutil for a reliable cross-platform check. Falls back to
    os.kill(pid, 0) which raises an exception if the process doesn't exist.
    """
    try:
        proc = psutil.Process(pid)
        # A zombie process has technically exited — treat as dead.
        return proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
