# =============================================================================
# sds/setup/deps.py — System and Python dependency installer
# =============================================================================
# This module handles all dependency installation:
#   1. Python packages — reads requirements.txt and runs pip install.
#   2. git — checks if installed; installs via Homebrew (macOS) or apt.
#   3. VSCode CLI (`code`) — checks if installed; downloads the server CLI.
#
# Every operation is idempotent: it checks whether the tool is already
# present before attempting installation. Running this twice is safe.
#
# `install_all()` is the public entry point called by the onboarding wizard.
# =============================================================================

import platform
import shutil
import subprocess
import sys
from pathlib import Path

from sds.config import PROJECT_ROOT
from sds.ui.console import console, print_success, print_info, print_warning, print_error

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"

# VSCode CLI download URLs for the server variant (not the desktop app).
# These are used only if `code` is not already on PATH.
VSCODE_CLI_URLS = {
    "Darwin":  "https://code.visualstudio.com/sha/download?build=stable&os=cli-darwin-arm64",
    "Linux":   "https://code.visualstudio.com/sha/download?build=stable&os=cli-linux-x64",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def install_all() -> None:
    """
    Run all installation checks and installs.

    Called by the onboarding wizard and the `start` command (as a
    pre-flight check to ensure nothing is missing).
    """
    _check_python_version()
    install_python_packages()
    install_git()
    install_vscode_cli()


# ---------------------------------------------------------------------------
# Python version check
# ---------------------------------------------------------------------------

def _check_python_version() -> None:
    """Ensure we're running Python 3.10 or newer."""
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        raise RuntimeError(
            f"Python 3.10+ required. You are running {major}.{minor}.\n"
            "  Please upgrade Python and try again."
        )
    print_info(f"Python {major}.{minor} — OK")


# ---------------------------------------------------------------------------
# Python packages
# ---------------------------------------------------------------------------

def install_python_packages() -> None:
    """
    Run `pip install -r requirements.txt` to ensure all Python deps are met.

    This uses the SAME Python interpreter that is running this script,
    which ensures packages land in the correct virtual environment.
    """
    if not REQUIREMENTS_FILE.exists():
        print_warning(f"requirements.txt not found at {REQUIREMENTS_FILE}. Skipping.")
        return

    print_info("Installing Python packages from requirements.txt ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE), "--quiet"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"pip install failed:\n{result.stderr}"
        )

    print_success("Python packages installed.")


def update_requirements(package_specs: list[str]) -> None:
    """
    Add one or more package specs to requirements.txt if not already present,
    then run pip install to install them.

    Args:
        package_specs: List of pip-style specs, e.g. ["pandas>=2.0", "numpy"].
    """
    if not REQUIREMENTS_FILE.exists():
        REQUIREMENTS_FILE.write_text("# Auto-generated requirements\n")

    existing = REQUIREMENTS_FILE.read_text()
    added = []

    for spec in package_specs:
        # Extract the package name (before any version specifier).
        pkg_name = spec.split(">=")[0].split("==")[0].split("<")[0].strip()
        if pkg_name.lower() not in existing.lower():
            added.append(spec)

    if added:
        with REQUIREMENTS_FILE.open("a") as f:
            for spec in added:
                f.write(f"\n{spec}")
        print_info(f"Added to requirements.txt: {', '.join(added)}")
        install_python_packages()
    else:
        print_info("All specified packages already in requirements.txt.")


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------

def install_git() -> None:
    """
    Check if git is installed. If not, attempt installation.

    Installation method depends on the OS:
    - macOS: Homebrew (`brew install git`). Falls back to Xcode CLI tools.
    - Linux: apt-get.
    - Other: Print instructions and raise.
    """
    if shutil.which("git"):
        # git is already on PATH — nothing to do.
        result = subprocess.run(["git", "--version"], capture_output=True, text=True)
        print_info(f"git — {result.stdout.strip()}")
        return

    print_info("git not found. Attempting installation ...")

    system = platform.system()

    if system == "Darwin":
        # Try Homebrew first; fall back to xcode-select.
        if shutil.which("brew"):
            _run_or_raise(["brew", "install", "git"], "Homebrew git install failed.")
        else:
            console.print(
                "  [yellow]Homebrew not found. Attempting Xcode Command Line Tools...[/yellow]"
            )
            # xcode-select --install is interactive; we trigger it and wait.
            subprocess.run(["xcode-select", "--install"], check=False)
            print_warning(
                "Xcode CLI tools installation may require your interaction.\n"
                "  Once complete, re-run [bold cyan]python main.py onboard[/bold cyan]."
            )

    elif system == "Linux":
        _run_as_root(["apt-get", "install", "-y", "git"])

    else:
        raise RuntimeError(
            f"Unsupported OS: {system}. Please install git manually and re-run."
        )

    if shutil.which("git"):
        print_success("git installed.")
    else:
        raise RuntimeError("git installation appears to have failed. Install it manually.")


# ---------------------------------------------------------------------------
# VSCode CLI
# ---------------------------------------------------------------------------

def install_vscode_cli() -> None:
    """
    Check if the `code` CLI is available. If not, download the server CLI.

    The VSCode server CLI (distinct from the desktop app's `code` binary)
    is what we use for `code tunnel`. It's a single static binary.
    """
    if shutil.which("code"):
        # `code` is on PATH. Verify it supports `tunnel` subcommand.
        result = subprocess.run(
            ["code", "tunnel", "--help"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print_info("VSCode CLI (`code`) — found on PATH, tunnel supported.")
            return
        else:
            print_warning(
                "`code` is on PATH but may be the desktop app (not the server CLI).\n"
                "  Tunnel may still work. If it doesn't, install the VSCode server CLI."
            )
            return

    print_info("VSCode CLI not found. Downloading server CLI ...")

    system = platform.system()
    url = VSCODE_CLI_URLS.get(system)

    if not url:
        raise RuntimeError(
            f"Cannot auto-install VSCode CLI on {system}.\n"
            "  Download manually from https://code.visualstudio.com/docs/remote/tunnels"
        )

    # Download to a temp location, extract, and move to ~/bin.
    import tempfile, tarfile, urllib.request

    bin_dir = Path.home() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest = bin_dir / "code"

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / "code_cli.tar.gz"

        print_info(f"Downloading from {url} ...")
        urllib.request.urlretrieve(url, archive_path)

        print_info("Extracting archive ...")
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(tmp)

        # The archive contains a single `code` binary.
        extracted = list(Path(tmp).glob("code"))
        if not extracted:
            raise RuntimeError("Could not find `code` binary in downloaded archive.")

        shutil.move(str(extracted[0]), str(dest))
        dest.chmod(0o755)

    # Add ~/bin to PATH for this session.
    os.environ["PATH"] = str(bin_dir) + ":" + os.environ.get("PATH", "")

    if shutil.which("code"):
        print_success(f"VSCode CLI installed to {dest}")
        console.print(
            f"  [dim]Add [bold]{bin_dir}[/bold] to your PATH in ~/.zshrc or ~/.bashrc[/dim]"
        )
    else:
        raise RuntimeError(
            f"VSCode CLI was installed to {dest} but `code` is not on PATH.\n"
            f"  Add {bin_dir} to your PATH and try again."
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_or_raise(cmd: list[str], error_msg: str) -> None:
    """Run a shell command; raise RuntimeError with error_msg on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{error_msg}\n{result.stderr}")


def _run_as_root(cmd: list[str]) -> None:
    """Run a command with sudo; prompt the user for their password."""
    import os as _os
    full_cmd = ["sudo"] + cmd if _os.geteuid() != 0 else cmd
    result = subprocess.run(full_cmd)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(full_cmd)}")


# Make `os` available in _run_as_root (referenced before import at module top).
import os
