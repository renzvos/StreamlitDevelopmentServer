# =============================================================================
# sds/setup/git_setup.py — Git configuration and repository management
# =============================================================================
# This module handles everything git-related:
#   1. Configuring git (user.name, user.email, credential helper).
#   2. Cloning the repository on first run.
#   3. Pulling the latest changes on subsequent runs.
#
# It reads all values from sds/config.cfg — run onboarding first.
# It uses the GitPython library for programmatic git operations where possible,
# and subprocess for git config (GitPython doesn't expose all config commands).
# =============================================================================

import subprocess
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import git  # GitPython
from git.exc import GitCommandError, InvalidGitRepositoryError

from sds.config import cfg
from sds.ui.console import print_info, print_success, print_warning, print_error


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def setup_git() -> None:
    """
    Run the full git setup: configure + clone/pull.

    Called by the onboarding wizard after values are written to .env.
    Safe to call multiple times — it checks state before acting.
    """
    _configure_git_globals()
    _clone_or_pull_repo()


# ---------------------------------------------------------------------------
# Global git configuration
# ---------------------------------------------------------------------------

def _configure_git_globals() -> None:
    """
    Set global git configuration: user.name, user.email, credential helper.

    We set these globally (not per-repo) so any git operation in the shell
    works without additional prompts.
    """
    # Skip if name/email not configured yet (defensive — should always be set
    # after onboarding step 2).
    if not cfg.git_username or not cfg.git_email:
        print_warning("Git username or email not configured. Skipping git config.")
        return

    _git_config("user.name", cfg.git_username)
    _git_config("user.email", cfg.git_email)
    print_success(f"Git identity set: {cfg.git_username} <{cfg.git_email}>")

    # Set credential helper to store tokens in the OS keychain.
    # On macOS: osxkeychain. On Linux: store (plaintext fallback).
    import platform
    if platform.system() == "Darwin":
        _git_config("credential.helper", "osxkeychain")
    else:
        # On Linux, use the git credential store (writes to ~/.git-credentials).
        # For production use, consider installing gnome-keyring or similar.
        _git_config("credential.helper", "store")

    print_info("Git credential helper configured.")


def _git_config(key: str, value: str) -> None:
    """Set a single global git config key to value via subprocess."""
    result = subprocess.run(
        ["git", "config", "--global", key, value],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print_warning(f"git config {key} failed: {result.stderr.strip()}")


# ---------------------------------------------------------------------------
# Repository clone / pull
# ---------------------------------------------------------------------------

def _clone_or_pull_repo() -> None:
    """
    Ensure the configured repository exists locally.

    - If the repo folder doesn't exist: clone.
    - If it exists and is a valid git repo: pull.
    - If it exists but is NOT a git repo: warn and skip.
    """
    if not cfg.git_repo_url:
        print_warning("GIT_REPO_URL not set. Skipping clone/pull.")
        return

    repo_path = cfg.repo_folder

    if repo_path.exists():
        # Check if it's a valid git repository.
        try:
            repo = git.Repo(repo_path)
            _pull_repo(repo)
        except InvalidGitRepositoryError:
            print_warning(
                f"{repo_path} exists but is not a git repository.\n"
                "  Remove it manually and re-run if you want a fresh clone."
            )
    else:
        _clone_repo(repo_path)


def _clone_repo(dest: Path) -> None:
    """
    Clone the configured repository to `dest`.

    If a GIT_TOKEN is configured, it is embedded in the HTTPS URL so that
    no interactive password prompt appears. SSH URLs are used as-is.
    """
    url = _authenticated_url(cfg.git_repo_url, cfg.git_token)
    print_info(f"Cloning repository to {dest} ...")
    print_info(f"  Branch: {cfg.git_branch}")

    try:
        git.Repo.clone_from(
            url,
            dest,
            branch=cfg.git_branch,
            # Show progress in the terminal.
            progress=_GitProgress(),
        )
        print_success(f"Repository cloned to {dest}")
    except GitCommandError as exc:
        # Mask the token in error output.
        safe_msg = str(exc).replace(cfg.git_token, "***TOKEN***") if cfg.git_token else str(exc)
        raise RuntimeError(f"Clone failed: {safe_msg}") from exc


def _pull_repo(repo: git.Repo) -> None:
    """
    Pull the latest changes for the configured branch.

    Handles detached HEAD gracefully (e.g. after a manual checkout).
    """
    print_info(f"Repository exists. Pulling latest changes on '{cfg.git_branch}' ...")
    try:
        origin = repo.remotes["origin"]
        # Update the remote URL in case the token has been rotated.
        new_url = _authenticated_url(cfg.git_repo_url, cfg.git_token)
        origin.set_url(new_url)
        origin.pull(cfg.git_branch)
        print_success("Repository up to date.")
    except GitCommandError as exc:
        safe_msg = str(exc).replace(cfg.git_token, "***TOKEN***") if cfg.git_token else str(exc)
        print_warning(f"Pull failed (non-fatal): {safe_msg}")
        print_warning("Continuing with existing local state.")


# ---------------------------------------------------------------------------
# Runtime helpers called by other modules
# ---------------------------------------------------------------------------

def clone_or_pull() -> None:
    """
    Public shortcut for triggering a clone or pull outside of onboarding.
    Used by the `start` command to ensure the repo is fresh.
    """
    _clone_or_pull_repo()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _authenticated_url(url: str, token: str) -> str:
    """
    Embed a GitHub token into an HTTPS URL for passwordless clone/pull.

    Converts: https://github.com/user/repo.git
    To:       https://<token>@github.com/user/repo.git

    SSH URLs are returned unchanged (they use key-based auth).
    """
    if not token or url.startswith("git@") or url.startswith("ssh://"):
        return url

    parsed = urlparse(url)
    # Replace netloc with token@host, preserving the rest of the URL.
    authenticated = parsed._replace(netloc=f"{token}@{parsed.netloc}")
    return urlunparse(authenticated)


class _GitProgress(git.RemoteProgress):
    """
    Simple RemoteProgress handler that prints git clone progress to stdout.
    GitPython calls update() during clone/fetch operations.
    """

    def update(self, op_code, cur_count, max_count=None, message=""):
        # Print a compact progress indicator; \r overwrites the same line.
        if max_count:
            pct = int((cur_count / max_count) * 100)
            print(f"\r  Cloning ... {pct}%  ", end="", flush=True)
        elif message:
            print(f"\r  {message}  ", end="", flush=True)

    def __del__(self):
        # Newline after the progress line finishes.
        print()
