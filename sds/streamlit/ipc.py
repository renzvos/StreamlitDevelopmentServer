# =============================================================================
# sds/streamlit/ipc.py — Unix Socket IPC (server + client)
# =============================================================================
# This module implements a lightweight inter-process communication layer
# using a Unix domain socket. It enables the `attach` command to stream
# live Streamlit logs from the running daemon to a separate terminal.
#
# ARCHITECTURE
# ─────────────
# Server side (runs in the daemon process):
#   - IPCServer binds to the Unix socket file.
#   - Each connecting client gets a thread that streams new log lines.
#   - Also accepts command messages: STOP, STATUS, RESTART.
#
# Client side (runs in the `attach` CLI command):
#   - IPCClient connects to the socket.
#   - Reads log lines and prints them via Rich Live.
#   - Can also send commands to the server.
#
# MESSAGE PROTOCOL
# ─────────────────
# All messages are UTF-8 JSON terminated by a newline character (\n).
# Commands (client → server):  {"cmd": "attach" | "stop" | "status" | "restart"}
# Log lines (server → client): {"type": "log", "line": "..."}
# Status response:             {"type": "status", "data": {...}}
# Control response:            {"type": "ack", "msg": "..."}
# EOF (daemon is shutting down): {"type": "eof"}
# =============================================================================

import json
import socket
import threading
from pathlib import Path
from typing import Optional, Callable

from sds.config import cfg
from sds.ui.console import print_info, print_warning, print_error


# ---------------------------------------------------------------------------
# IPC Server (runs inside the daemon process)
# ---------------------------------------------------------------------------

class IPCServer:
    """
    Unix socket server embedded in the Streamlit daemon process.

    Accepts connections from IPCClient instances (the `attach` command).
    For each connection, spawns a thread that:
    - Streams log lines from the shared deque to the client.
    - Receives command messages from the client.
    """

    def __init__(self, socket_path: Path, get_status_fn: Callable, control_fn: Callable):
        """
        Args:
            socket_path: Path to the Unix socket file.
            get_status_fn: Callable returning a status dict (for STATUS cmd).
            control_fn: Callable(str) for daemon control (STOP, RESTART).
        """
        self.socket_path = socket_path
        self.get_status = get_status_fn
        self.control = control_fn

        # Thread-safe list of log lines. The daemon appends here;
        # client threads read from here. We use a deque with maxlen so
        # memory doesn't grow unbounded for long-running sessions.
        from collections import deque
        self.log_buffer: deque[str] = deque(maxlen=5000)
        self._lock = threading.Lock()

        self._server_sock: Optional[socket.socket] = None
        self._running = False
        self._server_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """
        Bind the socket and start the accept-loop in a daemon thread.

        The thread is marked as daemon=True so it doesn't prevent the
        main process from exiting when Streamlit is stopped.
        """
        # Remove stale socket file from a previous run.
        if self.socket_path.exists():
            self.socket_path.unlink()

        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(str(self.socket_path))
        self._server_sock.listen(5)          # Allow up to 5 pending connections
        self._server_sock.settimeout(1.0)    # Non-blocking accept with 1s timeout
        self._running = True

        self._server_thread = threading.Thread(
            target=self._accept_loop,
            name="ipc-server",
            daemon=True,
        )
        self._server_thread.start()

    def stop(self) -> None:
        """Stop the IPC server and clean up the socket file."""
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError:
                pass

    def append_log(self, line: str) -> None:
        """
        Add a log line to the buffer.

        Called by the daemon whenever Streamlit produces output.
        Thread-safe via the internal lock.
        """
        with self._lock:
            self.log_buffer.append(line)

    # --- Private: accept loop ---

    def _accept_loop(self) -> None:
        """Accept incoming connections in a loop until stop() is called."""
        while self._running:
            try:
                conn, _ = self._server_sock.accept()
            except socket.timeout:
                continue   # Normal — just re-check _running
            except OSError:
                break

            # Each connection gets its own thread.
            t = threading.Thread(
                target=self._handle_client,
                args=(conn,),
                daemon=True,
            )
            t.start()

    def _handle_client(self, conn: socket.socket) -> None:
        """
        Handle a single client connection.

        Reads the initial command, then either:
        - "attach": streams log lines back to the client until disconnected.
        - "status": sends current status dict and closes connection.
        - "stop"/"restart": forwards to daemon control, sends ack.
        """
        try:
            conn.settimeout(5.0)
            raw = _recv_line(conn)
            if not raw:
                return

            msg = json.loads(raw)
            cmd = msg.get("cmd", "").lower()

            if cmd == "attach":
                self._stream_logs(conn)

            elif cmd == "status":
                status_data = self.get_status()
                _send(conn, {"type": "status", "data": status_data})

            elif cmd in ("stop", "restart"):
                _send(conn, {"type": "ack", "msg": f"Executing {cmd}..."})
                self.control(cmd)

            else:
                _send(conn, {"type": "error", "msg": f"Unknown command: {cmd}"})

        except (json.JSONDecodeError, OSError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _stream_logs(self, conn: socket.socket) -> None:
        """
        Stream buffered + live log lines to the attached client.

        First sends the last N buffered lines (so the client sees recent
        history), then streams new lines as they arrive.
        """
        # Snapshot the current buffer for the initial backfill.
        with self._lock:
            backfill = list(self.log_buffer)

        # Send backfill lines.
        for line in backfill:
            if not _send(conn, {"type": "log", "line": line}):
                return

        # Now track the buffer length and send new lines as they come in.
        last_len = len(backfill)

        while self._running:
            with self._lock:
                current_buffer = list(self.log_buffer)

            current_len = len(current_buffer)
            if current_len > last_len:
                # New lines since last check.
                for line in current_buffer[last_len:]:
                    if not _send(conn, {"type": "log", "line": line}):
                        return
                last_len = current_len

            import time; time.sleep(0.1)

        # Daemon is stopping — send EOF marker.
        _send(conn, {"type": "eof"})


# ---------------------------------------------------------------------------
# IPC Client (runs in the `attach` CLI command)
# ---------------------------------------------------------------------------

class IPCClient:
    """
    Unix socket client used by `python main.py attach`.

    Connects to the running daemon's socket and streams log lines to
    the terminal using Rich Live.
    """

    def __init__(self, socket_path: Optional[Path] = None):
        self.socket_path = socket_path or cfg.socket_file
        self._sock: Optional[socket.socket] = None

    def connect(self) -> bool:
        """
        Connect to the IPC server.

        Returns:
            True on success, False if the socket is not available
            (meaning the daemon is not running).
        """
        if not self.socket_path.exists():
            print_error(
                "No IPC socket found. Is Streamlit running?\n"
                "  Start it with: [bold cyan]python main.py streamlit start[/bold cyan]"
            )
            return False

        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(str(self.socket_path))
            return True
        except OSError as exc:
            print_error(f"Cannot connect to Streamlit daemon: {exc}")
            return False

    def attach(self) -> None:
        """
        Stream live log output to the terminal.

        This call blocks until the daemon stops or the user presses Ctrl+C.
        Prints each line using Rich for coloured output.
        """
        if not self._sock and not self.connect():
            return

        from rich.console import Console
        from rich.text import Text
        live_console = Console()

        # Send ATTACH command to the server.
        _send(self._sock, {"cmd": "attach"})

        live_console.print("[bold cyan]─── Attached to Streamlit (Ctrl+C to detach) ───[/bold cyan]")

        try:
            while True:
                raw = _recv_line(self._sock)
                if not raw:
                    live_console.print("[dim]Connection closed by daemon.[/dim]")
                    break

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    live_console.print(raw)
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "log":
                    line = msg.get("line", "")
                    # Colour-code common Streamlit log patterns.
                    _print_log_line(live_console, line)

                elif msg_type == "eof":
                    live_console.print("[bold yellow]Streamlit process ended.[/bold yellow]")
                    break

                elif msg_type == "error":
                    live_console.print(f"[red]Error: {msg.get('msg')}[/red]")
                    break

        except KeyboardInterrupt:
            live_console.print("\n[dim]Detached.[/dim]")
        finally:
            self.close()

    def send_command(self, cmd: str) -> Optional[dict]:
        """
        Send a control command (stop/restart/status) to the daemon.

        Returns:
            The response dict from the server, or None on failure.
        """
        if not self._sock and not self.connect():
            return None

        _send(self._sock, {"cmd": cmd})
        raw = _recv_line(self._sock)
        if not raw:
            return None

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def close(self) -> None:
        """Close the socket connection."""
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


# ---------------------------------------------------------------------------
# Low-level socket helpers
# ---------------------------------------------------------------------------

def _send(sock: socket.socket, data: dict) -> bool:
    """
    Serialize `data` to JSON and send it over the socket with a newline.

    Returns True on success, False if the socket was closed.
    """
    try:
        line = json.dumps(data) + "\n"
        sock.sendall(line.encode("utf-8"))
        return True
    except OSError:
        return False


def _recv_line(sock: socket.socket) -> Optional[str]:
    """
    Read a newline-terminated JSON line from the socket.

    Reads byte by byte until a newline is encountered.
    Returns None if the connection was closed.
    """
    buf = b""
    try:
        while True:
            chunk = sock.recv(1)
            if not chunk:
                return None
            if chunk == b"\n":
                return buf.decode("utf-8")
            buf += chunk
    except OSError:
        return None


def _print_log_line(console, line: str) -> None:
    """
    Print a Streamlit log line with colour-coding based on content.

    Streamlit log format:  2024-01-01 00:00:00,000 INFO ...
    """
    from rich.text import Text

    text = Text(line)

    if "ERROR" in line or "error" in line.lower():
        text.stylize("bold red")
    elif "WARNING" in line or "warning" in line.lower():
        text.stylize("yellow")
    elif "INFO" in line:
        text.stylize("dim white")
    elif "You can now view" in line or "Local URL" in line or "Network URL" in line:
        text.stylize("bold green")
    else:
        text.stylize("white")

    console.print(text)
