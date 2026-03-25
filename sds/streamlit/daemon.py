# =============================================================================
# sds/streamlit/daemon.py — Single-instance Streamlit process manager
# =============================================================================
# This module is the core of the development server management.
# It enforces a SINGLE running instance of Streamlit at any time.
#
# SINGLE-INSTANCE ENFORCEMENT
# ────────────────────────────
# A PID file is written when Streamlit starts. Before starting a new instance,
# the daemon checks the PID file and verifies the process is still alive (using
# psutil). If the process is alive, start() refuses to launch a second instance.
# Only one instance can run at a time.
#
# PROCESS LIFECYCLE
# ──────────────────
# start()   → validate entry file → check no existing instance
#           → spawn `streamlit run` as subprocess
#           → write PID file
#           → start log-capture thread
#           → start IPC socket server
#
# stop()    → read PID → SIGTERM → wait → SIGKILL if needed
#           → stop IPC server → clean up PID + socket files
#
# restart() → stop() then start()
#
# LOG CAPTURE
# ────────────
# Streamlit stdout+stderr are captured by a background thread and written
# to logs/streamlit.log AND pushed into the IPC server's log buffer.
# This allows both persistent logging and live streaming via `attach`.
#
# DOCKER / VSCODE INTEROP
# ────────────────────────
# The daemon can be controlled from anywhere (VSCode tasks, Docker startup
# script, CLI) because control always goes through the PID file + IPC socket.
# The .vscode/tasks.json tasks call `python main.py streamlit start/stop`,
# which calls this module. Docker's start.py does the same.
# =============================================================================

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import psutil

from sds.config import cfg
from sds.streamlit.ipc import IPCServer
from sds.ui.console import print_info, print_success, print_warning, print_error


# ---------------------------------------------------------------------------
# Module-level daemon state
# ---------------------------------------------------------------------------
# These are set when this process is the one managing the Streamlit subprocess.
# In the `attach` or `stop` case, we read from the PID file instead.

_streamlit_proc: Optional[subprocess.Popen] = None
_ipc_server: Optional[IPCServer] = None
_log_thread: Optional[threading.Thread] = None
_is_daemon_process = False   # True only in the process that started Streamlit


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start() -> bool:
    """
    Start the Streamlit development server.

    Enforces single-instance: refuses to start if another instance is running.
    Starts the IPC server so that `attach` and VSCode tasks can communicate.

    Returns:
        True if Streamlit started (or was already running), False on error.
    """
    global _streamlit_proc, _ipc_server, _log_thread, _is_daemon_process

    # --- Guard: already running? ---
    if is_running():
        pid = _read_pid()
        print_warning(
            f"Streamlit is already running (PID {pid}).\n"
            f"  Use [bold cyan]python main.py attach[/bold cyan] to stream logs.\n"
            f"  Use [bold cyan]python main.py streamlit restart[/bold cyan] to restart."
        )
        return True

    # --- Guard: entry file exists? ---
    entry = cfg.streamlit_entry_point
    if not entry.exists():
        print_error(
            f"Streamlit entry file not found: [bold]{entry}[/bold]\n"
            f"  Ensure the repository is cloned and STREAMLIT_DEV_FILE is correct.\n"
            f"  Current setting: STREAMLIT_DEV_FILE={cfg.streamlit_dev_file}"
        )
        return False

    # --- Prepare log file ---
    log_file = cfg.log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)

    print_info(
        f"Starting Streamlit dev server\n"
        f"  File: [cyan]{entry}[/cyan]\n"
        f"  Port: [cyan]{cfg.streamlit_port}[/cyan]\n"
        f"  Logs: [cyan]{log_file}[/cyan]"
    )

    # --- Spawn Streamlit subprocess ---
    # We use stdout=PIPE + stderr=STDOUT to capture all output through a
    # single stream. A dedicated thread reads this stream and:
    #   a) Writes to the log file.
    #   b) Pushes to the IPC buffer for live streaming.
    try:
        _streamlit_proc = subprocess.Popen(
            [
                sys.executable, "-m", "streamlit", "run",
                str(entry),
                "--server.port", str(cfg.streamlit_port),
                "--server.address", cfg.streamlit_host,
                "--server.headless", "true",       # Suppress browser auto-open
                "--logger.level", "info",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,   # Line-buffered for real-time output
            # Do NOT use start_new_session=True here — we want to be the
            # parent process so we can capture the child's output.
        )
    except FileNotFoundError:
        print_error(
            "Streamlit is not installed. Run:\n"
            "  [bold cyan]pip install -r requirements.txt[/bold cyan]"
        )
        return False
    except OSError as exc:
        print_error(f"Failed to start Streamlit: {exc}")
        return False

    # --- Write PID file ---
    _write_pid(_streamlit_proc.pid)
    _is_daemon_process = True

    # --- Start IPC server ---
    _ipc_server = IPCServer(
        socket_path=cfg.socket_file,
        get_status_fn=status,
        control_fn=_handle_ipc_command,
    )
    _ipc_server.start()

    # --- Start log capture thread ---
    _log_thread = threading.Thread(
        target=_capture_logs,
        args=(log_file,),
        name="streamlit-log-capture",
        daemon=True,
    )
    _log_thread.start()

    # Give Streamlit a moment to start up.
    time.sleep(2)

    if not is_running():
        print_error(
            "Streamlit exited immediately after starting.\n"
            f"  Check logs: {log_file}"
        )
        _cleanup()
        return False

    print_success(
        f"Streamlit running on port [bold cyan]{cfg.streamlit_port}[/bold cyan] "
        f"(PID {_streamlit_proc.pid})\n"
        f"  [bold]Local:[/bold]   http://localhost:{cfg.streamlit_port}\n"
        f"  [bold]Network:[/bold] http://0.0.0.0:{cfg.streamlit_port}"
    )
    return True


def stop() -> bool:
    """
    Stop the running Streamlit process.

    Works whether or not this Python process started Streamlit — it reads
    the PID from the PID file. This is how VSCode tasks and Docker can
    stop Streamlit even if the original start was from a different shell.

    Returns:
        True on success, False on error.
    """
    global _streamlit_proc, _is_daemon_process

    if not is_running():
        print_info("Streamlit is not running.")
        _cleanup()
        return True

    pid = _read_pid()
    if pid is None:
        print_warning("No PID file found.")
        return False

    print_info(f"Stopping Streamlit (PID {pid}) ...")

    try:
        # Graceful shutdown: SIGTERM first.
        os.kill(pid, signal.SIGTERM)

        # Wait up to 10 seconds for graceful exit.
        for _ in range(20):
            time.sleep(0.5)
            if not _pid_is_alive(pid):
                break
        else:
            # Force kill if graceful shutdown timed out.
            print_warning("Streamlit didn't exit gracefully. Force killing ...")
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            time.sleep(1)

    except ProcessLookupError:
        pass   # Process was already gone.
    except PermissionError as exc:
        print_error(f"Permission denied: {exc}")
        return False

    # If this process started Streamlit, also terminate the Popen object.
    if _streamlit_proc and _is_daemon_process:
        try:
            _streamlit_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _streamlit_proc.kill()

    _cleanup()
    print_success("Streamlit stopped.")
    return True


def restart() -> bool:
    """
    Stop then start the Streamlit process.

    Returns:
        True if restart was successful, False if start or stop failed.
    """
    print_info("Restarting Streamlit ...")
    if is_running():
        if not stop():
            return False
        # Brief pause to allow port to be released.
        time.sleep(1)
    return start()


def status() -> dict:
    """
    Return a status dict describing the current Streamlit state.

    Returns:
        {
            "running": bool,
            "pid": int | None,
            "port": int,
            "entry_file": str,
            "url": str | None,
            "uptime_seconds": float | None,
        }
    """
    pid = _read_pid()
    running = pid is not None and _pid_is_alive(pid)

    uptime = None
    if running and pid:
        try:
            proc = psutil.Process(pid)
            uptime = time.time() - proc.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            running = False

    return {
        "running": running,
        "pid": pid if running else None,
        "port": cfg.streamlit_port,
        "entry_file": str(cfg.streamlit_entry_point),
        "url": f"http://localhost:{cfg.streamlit_port}" if running else None,
        "uptime_seconds": uptime,
    }


def is_running() -> bool:
    """Return True if the Streamlit process is alive."""
    pid = _read_pid()
    return pid is not None and _pid_is_alive(pid)


def wait_forever() -> None:
    """
    Block until the Streamlit process exits.

    Called by Docker's start.py to keep the container alive as long as
    Streamlit is running. In CLI mode, the user can Ctrl+C to exit.
    """
    pid = _read_pid()
    if not pid:
        return

    print_info("Watching Streamlit process. Press Ctrl+C to stop.")
    try:
        while _pid_is_alive(pid):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    print_info("Streamlit process ended.")


# ---------------------------------------------------------------------------
# Log capture (background thread)
# ---------------------------------------------------------------------------

def _capture_logs(log_file: Path) -> None:
    """
    Read Streamlit subprocess output line-by-line.

    Runs in a background thread. For each line:
    1. Appends to the log file on disk.
    2. Pushes to the IPC server's log buffer (for live streaming).

    Exits when the subprocess terminates (stdout closes).
    """
    global _ipc_server

    with open(log_file, "a", encoding="utf-8") as f:
        for line in _streamlit_proc.stdout:
            # Strip trailing newline for consistent storage.
            clean_line = line.rstrip("\n")

            # Write to disk log.
            f.write(clean_line + "\n")
            f.flush()

            # Push to IPC buffer for live streaming.
            if _ipc_server:
                _ipc_server.append_log(clean_line)


# ---------------------------------------------------------------------------
# IPC command handler
# ---------------------------------------------------------------------------

def _handle_ipc_command(cmd: str) -> None:
    """
    Called by the IPC server when a client sends a control command.

    Args:
        cmd: "stop" or "restart"
    """
    if cmd == "stop":
        stop()
    elif cmd == "restart":
        restart()


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------

def _write_pid(pid: int) -> None:
    cfg.pid_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.pid_file.write_text(str(pid))


def _read_pid() -> Optional[int]:
    try:
        return int(cfg.pid_file.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _remove_pid() -> None:
    try:
        cfg.pid_file.unlink(missing_ok=True)
    except OSError:
        pass


def _pid_is_alive(pid: int) -> bool:
    """Check whether a process with this PID is alive using psutil."""
    try:
        proc = psutil.Process(pid)
        return proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _cleanup() -> None:
    """Remove PID file, stop IPC server, clean socket."""
    global _ipc_server, _is_daemon_process

    _remove_pid()

    if _ipc_server and _is_daemon_process:
        _ipc_server.stop()
        _ipc_server = None

    _is_daemon_process = False
