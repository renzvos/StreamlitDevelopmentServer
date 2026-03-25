#!/usr/bin/env python3
# =============================================================================
# docker/start.py — Docker container entrypoint
# =============================================================================
# This script is the CMD entrypoint when running in a Docker container.
# It replaces the onboarding wizard with a streamlined startup that reads
# all configuration from environment variables injected by `docker run -e`.
#
# What this script does:
#   1. Validates that required environment variables are present.
#   2. Runs git clone/pull to get the repository.
#   3. Installs Python packages (from requirements.txt).
#   4. Starts the Streamlit dev server.
#   5. Blocks (keeps the container alive) until the process exits.
#
# What it SKIPS (vs the full CLI):
#   - Identity fingerprint check (DOCKER_MODE=true bypasses it).
#   - VSCode tunnel (not typically used in Docker mode).
#   - Microsoft auth (tunnel not running).
#   - Interactive onboarding wizard.
#
# All configuration comes from environment variables. Pass them with:
#   docker run -e GIT_REPO_URL=... -e GIT_TOKEN=... -e STREAMLIT_DEV_FILE=...
# =============================================================================

import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure sds package is importable from the project root.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Set DOCKER_MODE before importing any sds modules so the identity guard
# skips its checks. This must be set BEFORE sds.config is imported.
# ---------------------------------------------------------------------------
os.environ.setdefault("DOCKER_MODE", "true")

# Now import sds modules.
from sds.config import cfg
from sds.ui.console import (
    console,
    print_banner,
    print_header,
    print_info,
    print_success,
    print_error,
    print_warning,
)
from sds.streamlit.daemon import start as streamlit_start, wait_forever


# ---------------------------------------------------------------------------
# Required environment variables for Docker mode
# ---------------------------------------------------------------------------

REQUIRED_VARS = [
    "GIT_REPO_URL",
    "STREAMLIT_DEV_FILE",
]


def validate_env() -> bool:
    """
    Check that all required environment variables are set.

    Returns True if all required vars are present, False otherwise.
    Missing vars are listed clearly so the user knows what to add.
    """
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v, "").strip()]

    if missing:
        print_error(
            "Missing required environment variables:\n" +
            "\n".join(f"  - {v}" for v in missing) +
            "\n\n"
            "  Pass them with: docker run -e VAR=value ..."
        )
        return False

    return True


def setup_git() -> bool:
    """
    Configure git and clone/pull the repository.

    Returns True on success, False on failure.
    """
    print_info("Setting up git and cloning repository ...")

    try:
        from sds.setup.git_setup import setup_git as _setup_git
        _setup_git()
        return True
    except Exception as exc:
        print_error(f"Git setup failed: {exc}")
        return False


def install_deps() -> bool:
    """
    Install Python packages from requirements.txt.

    Returns True on success, False on failure.
    """
    print_info("Installing Python dependencies ...")

    try:
        from sds.setup.deps import install_python_packages
        install_python_packages()
        return True
    except Exception as exc:
        print_error(f"Dependency install failed: {exc}")
        return False


def main() -> int:
    """
    Main Docker startup sequence.

    Returns exit code (0 = success, 1 = failure).
    """
    print_banner()
    print_header(
        "Docker Mode",
        "Starting Streamlit Development Machine in container...",
    )

    # Step 1 — Validate required environment.
    print_info("[1/4] Validating environment variables ...")
    if not validate_env():
        return 1
    print_success("Environment variables OK.")

    # Step 2 — Install Python dependencies.
    print_info("[2/4] Installing dependencies ...")
    if not install_deps():
        return 1

    # Step 3 — Git setup (configure + clone/pull).
    print_info("[3/4] Configuring git and cloning repository ...")
    if not setup_git():
        return 1

    # Step 4 — Start Streamlit.
    print_info("[4/4] Starting Streamlit dev server ...")
    if not streamlit_start():
        return 1

    # Print a summary of what's running.
    console.print()
    print_success(
        f"Container is ready!\n"
        f"  Streamlit:  http://0.0.0.0:{cfg.streamlit_port}\n"
        f"  Entry file: {cfg.streamlit_entry_point}"
    )
    console.print()

    # Block until Streamlit exits (keeps the container alive).
    # In Docker, if the main process exits, the container stops.
    wait_forever()

    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
