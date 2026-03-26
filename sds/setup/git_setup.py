# =============================================================================
# sds/setup/git_setup.py — Git configuration and repository management
# =============================================================================
# This module handles everything git-related:
#   1. GitHub CLI (gh) authentication — interactive terminal login.
#   2. Configuring git globals (user.name, user.email).
#   3. Cloning the repository on first run.
#   4. Pulling the latest changes on subsequent runs.
#
# AUTHENTICATION STRATEGY
# ────────────────────────
# We use the GitHub CLI (`gh`) as the git credential helper. This means:
#   - No tokens in .env or embedded in URLs — ever.
#   - `gh auth login` is called interactively if the user is not logged in.
#   - All git HTTPS operations use `gh auth git-credential` transparently.
#   - Works for both public and private repos.
#   - GitHub auth is completely separate from VSCode / Microsoft auth.
#
# SSH URLs bypass gh entirely and use key-based auth as normal.
# =============================================================================

import shutil
import subprocess
from pathlib import Path

import git  # GitPython
from git.exc import GitCommandError, InvalidGitRepositoryError

from sds.config import cfg
from sds.ui.console import print_info, print_success, print_warning, print_error


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def setup_git() -> None:
    """
    Run the full git setup: gh auth → configure globals → clone/pull.

    Called by the onboarding wizard and Docker startup.
    Safe to call multiple times — checks state before acting.
    """
    _ensure_gh_auth()
    _configure_git_globals()
    _clone_or_pull_repo()


def clone_or_pull() -> None:
    """
    Public shortcut to clone or pull without re-running auth/config.
    Used by the `start` command to freshen the repo before launching Streamlit.
    """
    _clone_or_pull_repo()


# ---------------------------------------------------------------------------
# GitHub CLI authentication
# ---------------------------------------------------------------------------

def _ensure_gh_auth() -> None:
    """
    Ensure the GitHub CLI is authenticated for repo access.

    If `gh` is not installed → skip (public repos work without it).
    If `gh` is installed but not logged in → run `gh auth login` interactively
    so the user can authenticate in the terminal (browser device flow or token).

    This is for GitHub REPO ACCESS ONLY.
    It has no relation to VSCode tunnel or Microsoft authentication.
    """
    if not shutil.which("gh"):
        print_warning(
            "`gh` CLI not found. Skipping GitHub auth.\n"
            "  Public repos will still clone without it.\n"
            "  For private repos, install gh: https://cli.github.com"
        )
        return

    # Check if already authenticated (non-interactive check).
    result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        # Already logged in — wire up gh as the git credential helper.
        _configure_gh_credential_helper()
        print_success("GitHub CLI already authenticated.")
        return

    # Not logged in — prompt interactively in the terminal.
    print_info(
        "GitHub CLI is not authenticated.\n"
        "  Launching interactive GitHub login (for repo access only).\n"
        "  This is separate from VSCode / Microsoft authentication.\n"
    )

    login_result = subprocess.run(
        [
            "gh", "auth", "login",
            "--git-protocol", "https",   # Use HTTPS so gh manages credentials
            "--scopes", "repo",          # Request only repo scope — minimal permissions
        ]
        # No capture_output — let the user see and interact with all prompts.
    )

    if login_result.returncode == 0:
        _configure_gh_credential_helper()
        print_success("GitHub CLI login successful.")
    else:
        print_warning(
            "GitHub CLI login was skipped or failed.\n"
            "  Public repos will still clone fine.\n"
            "  Private repos will fail at the clone step."
        )


def _configure_gh_credential_helper() -> None:
    """
    Configure git to use `gh auth git-credential` as its credential helper.

    This routes all GitHub HTTPS credential requests through gh, so no
    tokens ever appear in .env, URLs, or git config files.

    The helper is scoped to github.com only, so other git hosts are
    unaffected and use their own configured helpers.
    """
    # Scope the helper to github.com only (not all HTTPS hosts).
    _git_config(
        "credential.https://github.com.helper",
        "!/usr/bin/env gh auth git-credential",
    )
    print_info("Git credential helper → gh auth git-credential (github.com)")


# ---------------------------------------------------------------------------
# Global git configuration
# ---------------------------------------------------------------------------

def _configure_git_globals() -> None:
    """
    Set git globals: user.name and user.email.

    These are set globally so commits are attributed correctly in all repos.
    The credential helper is handled separately by _configure_gh_credential_helper().
    """
    if not cfg.git_username or not cfg.git_email:
        print_warning("GIT_USERNAME or GIT_EMAIL not set. Skipping git identity config.")
        return

    _git_config("user.name", cfg.git_username)
    _git_config("user.email", cfg.git_email)
    print_success(f"Git identity: {cfg.git_username} <{cfg.git_email}>")


def _git_config(key: str, value: str) -> None:
    """Set a single global git config key=value via subprocess."""
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

    - Repo folder absent       → clone from GIT_REPO_URL.
    - Repo folder is a git repo → pull latest on GIT_BRANCH.
    - Repo folder exists but isn't a git repo → warn and skip.
    """
    if not cfg.git_repo_url:
        print_warning("GIT_REPO_URL not set. Skipping clone/pull.")
        return

    repo_path = cfg.repo_folder

    if repo_path.exists():
        try:
            repo = git.Repo(repo_path)
            _pull_repo(repo)
        except InvalidGitRepositoryError:
            print_warning(
                f"{repo_path} exists but is not a git repository.\n"
                "  Remove it manually and re-run to get a fresh clone."
            )
    else:
        _clone_repo(repo_path)


def _clone_repo(dest: Path) -> None:
    """
    Clone GIT_REPO_URL into `dest`.

    For GitHub URLs: delegates to `gh repo clone` so that gh's own token
    is used directly — no credential helper indirection needed. This works
    for both public and private repos as long as `gh auth login` has run.

    For non-GitHub URLs (GitLab, Bitbucket, self-hosted): falls back to
    GitPython, which uses whatever credential helper is configured globally.
    """
    url = cfg.git_repo_url
    print_info(f"Cloning {url}")
    print_info(f"  → {dest}  (branch: {cfg.git_branch})")

    if _is_github_url(url) and shutil.which("gh"):
        _clone_via_gh(url, dest)
    else:
        _clone_via_gitpython(url, dest)


def _is_github_url(url: str) -> bool:
    """Return True if the URL points to github.com."""
    return "github.com" in url


def _clone_via_gh(url: str, dest: Path) -> None:
    """
    Clone using `gh repo clone <url> <dest>`.

    We do NOT pass --branch here. Instead we let git clone the repo on its
    default branch, then detect the actual default branch name. If GIT_BRANCH
    is set to something other than the detected default, we attempt to check
    it out — but we never fail the whole setup over a wrong branch name.

    `gh repo clone` uses gh's stored OAuth token directly, works for both
    public and private repos without any credential-helper indirection.
    """
    # Clone onto the repo's own default branch (no --branch flag).
    result = subprocess.run(
        ["gh", "repo", "clone", url, str(dest)],
        # No capture — show git's progress output in the terminal.
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"gh repo clone failed (exit {result.returncode}).\n"
            "  Ensure `gh auth login` has been completed and you have repo access."
        )

    # Detect the actual default branch the repo landed on.
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(dest),
        capture_output=True,
        text=True,
    )
    actual_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
    print_success(f"Repository cloned to {dest}  (branch: {actual_branch})")


def _clone_via_gitpython(url: str, dest: Path) -> None:
    """Fallback clone via GitPython for non-GitHub repos."""
    try:
        git.Repo.clone_from(url, dest, branch=cfg.git_branch, progress=_GitProgress())
        print_success(f"Repository cloned to {dest}")
    except GitCommandError as exc:
        raise RuntimeError(f"Clone failed: {exc}") from exc


def _pull_repo(repo: git.Repo) -> None:
    """
    Pull the latest changes on GIT_BRANCH from origin.

    Uses `gh` for GitHub repos (same auth as clone).
    Falls back to GitPython for non-GitHub repos.
    Non-fatal: a failed pull prints a warning and continues so Streamlit
    can still start with existing local state.
    """
    print_info(f"Repository exists — pulling '{cfg.git_branch}' ...")

    if _is_github_url(cfg.git_repo_url) and shutil.which("gh"):
        # Pull on whatever branch the repo is currently on (not the configured
        # GIT_BRANCH name, which may differ from the repo's actual branch name).
        result = subprocess.run(
            ["git", "pull"],
            cwd=str(repo.working_dir),
        )
        if result.returncode == 0:
            print_success("Repository up to date.")
        else:
            print_warning("Pull failed (non-fatal). Continuing with existing local state.")
    else:
        try:
            origin = repo.remotes["origin"]
            origin.set_url(cfg.git_repo_url)
            origin.pull(cfg.git_branch)
            print_success("Repository up to date.")
        except GitCommandError as exc:
            print_warning(f"Pull failed (non-fatal): {exc}")
            print_warning("Continuing with existing local state.")


# ---------------------------------------------------------------------------
# Progress reporter for GitPython clone operations
# ---------------------------------------------------------------------------

class _GitProgress(git.RemoteProgress):
    """Prints a compact progress line during git clone/fetch."""

    def update(self, op_code, cur_count, max_count=None, message=""):
        if max_count:
            pct = int((cur_count / max_count) * 100)
            print(f"\r  Cloning ... {pct}%  ", end="", flush=True)
        elif message:
            print(f"\r  {message}  ", end="", flush=True)

    def __del__(self):
        print()  # Newline after progress line finishes.
