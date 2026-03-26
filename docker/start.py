#!/usr/bin/env python3
# =============================================================================
# docker/start.py — Docker container entrypoint
# =============================================================================
# Startup sequence inside the container:
#
#   [1/5] Validate required environment variables
#   [2/5] Install Python dependencies
#   [3/5] GitHub auth (gh auth login) + git clone/pull
#   [4/5] VSCode tunnel  ← Microsoft device-flow auth on first run, then starts
#   [5/5] Streamlit dev server
#
# Both the tunnel and Streamlit run concurrently:
#   - Tunnel runs as a detached background thread (keeps going until container stops)
#   - Streamlit runs in the foreground; the script blocks until it exits
#
# Authentication split (two independent systems):
#   - GitHub  → gh auth login   (repo access only)
#   - VSCode  → Microsoft device-flow via `code tunnel` (web editor access only)
#
# All config comes from docker.env:
#   docker run -it --env-file docker.env -p 8501:8501 streamlit-dev-machine
# =============================================================================

import os
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the sds package is importable from the project root.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Set DOCKER_MODE before any sds import so the identity guard is skipped.
# ---------------------------------------------------------------------------
os.environ.setdefault("DOCKER_MODE", "true")

from sds.config import cfg
from sds.ui.console import (
    console,
    print_banner,
    print_header,
    print_info,
    print_success,
    print_error,
    print_warning,
    print_status_table,
)
from sds.streamlit.daemon import start as streamlit_start, wait_forever


# ---------------------------------------------------------------------------
# Required environment variables
# ---------------------------------------------------------------------------

REQUIRED_VARS = [
    "GIT_REPO_URL",
    "STREAMLIT_DEV_FILE",
    "VSCODE_TUNNEL_NAME",
]


# ---------------------------------------------------------------------------
# Step functions
# ---------------------------------------------------------------------------

def validate_env() -> bool:
    """
    Ensure all required environment variables are present.
    Prints a clear list of anything missing.
    """
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v, "").strip()]
    if missing:
        print_error(
            "Missing required environment variables:\n" +
            "\n".join(f"  - {v}" for v in missing) +
            "\n\n  Add them to docker.env and re-run."
        )
        return False
    return True


def install_deps() -> bool:
    """Install Python packages from requirements.txt."""
    print_info("Installing Python dependencies ...")
    try:
        from sds.setup.deps import install_python_packages
        install_python_packages()
        return True
    except Exception as exc:
        print_error(f"Dependency install failed: {exc}")
        return False


def setup_github() -> bool:
    """
    Run gh auth + git config + clone/pull.

    `gh auth login` is triggered interactively if the user is not already
    authenticated. This covers GitHub repo access only — not VSCode/Microsoft.
    """
    print_info("Setting up GitHub auth and cloning repository ...")
    try:
        from sds.setup.git_setup import setup_git
        setup_git()
        return True
    except Exception as exc:
        print_error(f"Git/GitHub setup failed: {exc}")
        return False


def start_vscode_tunnel() -> bool:
    """
    Start the VSCode tunnel in a background thread.

    On first run, `code tunnel` prints a Microsoft device-flow URL+code to
    the terminal. The user must open the URL in a browser and enter the code.
    Subsequent runs reuse the cached token silently.

    The tunnel runs detached — it keeps running alongside Streamlit.
    Returns True immediately after the background thread is started.
    """
    from sds.tunnel.manager import start as tunnel_start, is_running

    if is_running():
        print_warning("VSCode tunnel is already running.")
        return True

    print_info(
        "Starting VSCode tunnel ...\n"
        "  On first run you will see a Microsoft login prompt below.\n"
        "  Open the URL in your browser and enter the code shown.\n"
        "  This is separate from your GitHub login above."
    )

    # Run the tunnel start in a background thread so it doesn't block
    # the Streamlit startup below. The tunnel process itself is detached
    # via start_new_session=True inside tunnel/manager.py.
    def _run_tunnel():
        success = tunnel_start()
        if success:
            print_success(
                f"VSCode tunnel running.\n"
                f"  Connect at: https://vscode.dev/tunnel/{cfg.vscode_tunnel_name}"
            )
        else:
            print_warning("VSCode tunnel failed to start. Streamlit will still run.")

    t = threading.Thread(target=_run_tunnel, name="tunnel-starter", daemon=True)
    t.start()

    # Give the tunnel a moment to emit the Microsoft auth prompt before
    # Streamlit output floods the terminal.
    time.sleep(3)

    return True


def start_streamlit() -> bool:
    """Start the Streamlit dev server (foreground — blocks until exit)."""
    print_info("Starting Streamlit dev server ...")
    return streamlit_start()


# ---------------------------------------------------------------------------
# Main startup sequence
# ---------------------------------------------------------------------------

def main() -> int:
    print_banner()
    print_header(
        "Docker Mode",
        f"repo: {os.environ.get('GIT_REPO_URL', '?')}  |  file: {os.environ.get('STREAMLIT_DEV_FILE', '?')}",
    )

    steps = [
        ("[1/5] Validating environment",          validate_env),
        ("[2/5] Installing dependencies",          install_deps),
        ("[3/5] GitHub auth + clone/pull",         setup_github),
        ("[4/5] VSCode tunnel",                    start_vscode_tunnel),
        ("[5/5] Starting Streamlit dev server",    start_streamlit),
    ]

    for label, fn in steps:
        console.print()
        print_info(label)
        if not fn():
            return 1

    # Print final status table.
    from sds.tunnel.manager import status as tunnel_status
    from sds.streamlit.daemon import status as st_status

    tn = tunnel_status()
    st = st_status()

    print_status_table([
        {
            "name": "Streamlit Dev Server",
            "status": "running" if st["running"] else "stopped",
            "detail": st.get("url", ""),
        },
        {
            "name": "VSCode Tunnel",
            "status": "running" if tn["running"] else "stopped",
            "detail": tn.get("url") or cfg.vscode_tunnel_name,
        },
    ])

    # Block until Streamlit exits — keeps the container alive.
    wait_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
