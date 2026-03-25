# =============================================================================
# sds/config.py — Configuration loader and validator
# =============================================================================
# This module is the single source of truth for all runtime configuration.
# It loads the .env file using python-dotenv, validates required fields, and
# exposes a typed Config dataclass that every other module imports.
#
# Usage:
#   from sds.config import cfg   ← import the singleton config object
#   cfg.streamlit_dev_file       ← access any setting as an attribute
# =============================================================================

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Locate project root (the directory containing main.py / this package)
# ---------------------------------------------------------------------------
# We walk up from this file to find the directory that contains .env.
# This makes the tool work regardless of the current working directory.
PROJECT_ROOT: Path = Path(__file__).parent.parent.resolve()

# Path to the .env file (not committed to git)
ENV_FILE: Path = PROJECT_ROOT / ".env"

# Path to the .env.template (committed; shown to users who haven't onboarded)
ENV_TEMPLATE: Path = PROJECT_ROOT / ".env.template"


def _load_env() -> None:
    """
    Load .env into os.environ.

    If .env doesn't exist, we don't raise immediately — the CLI handles
    that by routing the user to onboarding. We do load the template if
    it exists so that default values are available.
    """
    if ENV_FILE.exists():
        # override=True so .env values shadow any pre-existing env vars,
        # which prevents stale shell exports from interfering.
        load_dotenv(ENV_FILE, override=True)
    elif ENV_TEMPLATE.exists():
        # Fall back to template for defaults; most values will be empty.
        load_dotenv(ENV_TEMPLATE, override=False)


# Load immediately when this module is imported.
_load_env()


# ---------------------------------------------------------------------------
# Helper — read env var with optional default
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    """Return the value of an environment variable, falling back to default."""
    return os.environ.get(key, default).strip()


def _env_bool(key: str, default: bool = False) -> bool:
    """Return an env var interpreted as a boolean (true/1/yes → True)."""
    val = _env(key, "true" if default else "false").lower()
    return val in ("true", "1", "yes")


def _env_int(key: str, default: int = 0) -> int:
    """Return an env var interpreted as an integer."""
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Config dataclass — one instance holds all settings
# ---------------------------------------------------------------------------

@dataclass
class Config:
    """
    Typed container for all runtime configuration.

    Every field maps directly to an environment variable (documented inline).
    Accessing config values through this dataclass (instead of os.environ
    directly) gives us type safety and a single place to see all settings.
    """

    # --- Identity lock ---
    machine_fingerprint: str = field(default_factory=lambda: _env("MACHINE_FINGERPRINT"))
    allowed_user: str = field(default_factory=lambda: _env("ALLOWED_USER"))

    # --- Git ---
    git_username: str = field(default_factory=lambda: _env("GIT_USERNAME"))
    git_email: str = field(default_factory=lambda: _env("GIT_EMAIL"))
    git_token: str = field(default_factory=lambda: _env("GIT_TOKEN"))
    git_repo_url: str = field(default_factory=lambda: _env("GIT_REPO_URL"))
    git_branch: str = field(default_factory=lambda: _env("GIT_BRANCH", "main"))
    repo_folder: Path = field(
        default_factory=lambda: PROJECT_ROOT / _env("REPO_FOLDER", "repo")
    )

    # --- Streamlit dev server ---
    streamlit_dev_file: str = field(
        default_factory=lambda: _env("STREAMLIT_DEV_FILE", "litdev.py")
    )
    streamlit_port: int = field(
        default_factory=lambda: _env_int("STREAMLIT_PORT", 8501)
    )
    streamlit_host: str = field(
        default_factory=lambda: _env("STREAMLIT_HOST", "0.0.0.0")
    )

    # --- VSCode tunnel ---
    vscode_tunnel_name: str = field(
        default_factory=lambda: _env("VSCODE_TUNNEL_NAME", "streamlit-dev-machine")
    )

    # --- Microsoft auth ---
    ms_client_id: str = field(default_factory=lambda: _env("MS_CLIENT_ID"))
    ms_tenant_id: str = field(default_factory=lambda: _env("MS_TENANT_ID", "common"))
    ms_access_token: str = field(default_factory=lambda: _env("MS_ACCESS_TOKEN"))
    ms_refresh_token: str = field(default_factory=lambda: _env("MS_REFRESH_TOKEN"))
    ms_token_expiry: str = field(default_factory=lambda: _env("MS_TOKEN_EXPIRY"))

    # --- Runtime flags ---
    docker_mode: bool = field(default_factory=lambda: _env_bool("DOCKER_MODE"))
    auto_start: bool = field(default_factory=lambda: _env_bool("AUTO_START"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    # --- Runtime file paths ---
    pid_file: Path = field(
        default_factory=lambda: PROJECT_ROOT / _env("PID_FILE", ".streamlit.pid")
    )
    tunnel_pid_file: Path = field(
        default_factory=lambda: PROJECT_ROOT / _env("TUNNEL_PID_FILE", ".tunnel.pid")
    )
    socket_file: Path = field(
        default_factory=lambda: PROJECT_ROOT / _env("SOCKET_FILE", ".streamlit.sock")
    )
    log_file: Path = field(
        default_factory=lambda: PROJECT_ROOT / _env("LOG_FILE", "logs/streamlit.log")
    )

    # --- Derived helpers ---

    @property
    def is_configured(self) -> bool:
        """True if .env exists and has been populated by onboarding."""
        return ENV_FILE.exists() and bool(self.machine_fingerprint)

    @property
    def streamlit_entry_point(self) -> Path:
        """Absolute path to the Streamlit file that should be run."""
        return self.repo_folder / self.streamlit_dev_file

    def reload(self) -> None:
        """
        Re-read .env from disk and refresh all fields.
        Call this after onboarding writes new values to .env.
        """
        _load_env()
        # Rebuild all fields from fresh env
        fresh = Config()
        for f in self.__dataclass_fields__:  # type: ignore[attr-defined]
            setattr(self, f, getattr(fresh, f))


# ---------------------------------------------------------------------------
# Singleton — import `cfg` everywhere instead of constructing Config()
# ---------------------------------------------------------------------------

cfg = Config()


# ---------------------------------------------------------------------------
# Config file writer — used by onboarding to persist settings to .env
# ---------------------------------------------------------------------------

def write_env(values: dict[str, str]) -> None:
    """
    Write or update key=value pairs in the .env file.

    This function is additive: existing keys are updated in-place,
    new keys are appended at the bottom. Blank lines and comments are
    preserved. The file is created if it doesn't exist.

    Args:
        values: dict mapping env var names to string values.
    """
    # Build a dict of existing content so we can do in-place updates.
    existing_lines: list[str] = []
    existing_keys: set[str] = set()

    if ENV_FILE.exists():
        existing_lines = ENV_FILE.read_text().splitlines()
        for line in existing_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                existing_keys.add(key)

    # Update existing lines in-place.
    updated_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in values:
                # Replace the value, preserving the key.
                updated_lines.append(f"{key}={values[key]}")
                continue
        updated_lines.append(line)

    # Append keys that weren't in the file yet.
    new_keys = [k for k in values if k not in existing_keys]
    if new_keys:
        updated_lines.append("")  # blank line separator
        for key in new_keys:
            updated_lines.append(f"{key}={values[key]}")

    # Ensure the logs directory exists before writing the file.
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text("\n".join(updated_lines) + "\n")

    # Reload config singleton so callers see the new values immediately.
    cfg.reload()
