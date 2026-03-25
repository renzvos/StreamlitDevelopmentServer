# =============================================================================
# sds/ui/prompts.py — Questionary prompt wrappers
# =============================================================================
# This module wraps questionary to provide consistent styled prompts across
# the onboarding wizard and any other interactive flows.
#
# All functions return the user's answer or None if the user cancelled
# (Ctrl+C / Ctrl+D). Callers should check for None and handle gracefully.
#
# Usage:
#   from sds.ui.prompts import ask_text, ask_password, ask_confirm, ask_select
# =============================================================================

from typing import Optional

import questionary
from questionary import Style

# ---------------------------------------------------------------------------
# Shared questionary style
# ---------------------------------------------------------------------------
# This style is applied to every prompt to keep the visual language consistent
# with the Rich console output above.
PROMPT_STYLE = Style(
    [
        ("qmark", "fg:#3498db bold"),        # The "?" marker — blue
        ("question", "fg:#ffffff bold"),      # Question text — white bold
        ("answer", "fg:#2ecc71 bold"),        # User's typed answer — green
        ("pointer", "fg:#3498db bold"),       # Selection pointer — blue
        ("highlighted", "fg:#3498db bold"),   # Highlighted option — blue
        ("selected", "fg:#2ecc71"),           # Selected option — green
        ("instruction", "fg:#6c757d"),        # Hint text — grey
        ("text", "fg:#ffffff"),               # Body text — white
        ("disabled", "fg:#6c757d italic"),    # Disabled option — grey
    ]
)


# ---------------------------------------------------------------------------
# Text / password prompts
# ---------------------------------------------------------------------------

def ask_text(
    message: str,
    default: str = "",
    placeholder: str = "",
    validate: Optional[callable] = None,
) -> Optional[str]:
    """
    Ask the user to type a single-line text response.

    Args:
        message: The question to display.
        default: Pre-filled value (shown in brackets, used if user hits Enter).
        placeholder: Ghost text shown inside the input box.
        validate: Optional callable(str) → bool | str. Return True to accept,
                  or a string error message to reject.

    Returns:
        The user's input string, or None if they cancelled.
    """
    try:
        result = questionary.text(
            message,
            default=default,
            instruction=f"(default: {default})" if default and not placeholder else placeholder,
            validate=validate,
            style=PROMPT_STYLE,
        ).ask()
        return result  # questionary returns None on Ctrl+C
    except (KeyboardInterrupt, EOFError):
        return None


def ask_password(
    message: str,
    validate: Optional[callable] = None,
) -> Optional[str]:
    """
    Ask the user to type a password (input is masked with asterisks).

    Args:
        message: The question to display.
        validate: Optional validation callable.

    Returns:
        The password string, or None if cancelled.
    """
    try:
        return questionary.password(
            message,
            validate=validate,
            style=PROMPT_STYLE,
        ).ask()
    except (KeyboardInterrupt, EOFError):
        return None


# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------

def ask_confirm(message: str, default: bool = True) -> Optional[bool]:
    """
    Ask a yes/no confirmation question.

    Args:
        message: The question to display (e.g. "Continue?").
        default: Pre-selected answer (shown as [Y/n] or [y/N]).

    Returns:
        True for yes, False for no, or None if cancelled.
    """
    try:
        return questionary.confirm(
            message,
            default=default,
            style=PROMPT_STYLE,
        ).ask()
    except (KeyboardInterrupt, EOFError):
        return None


# ---------------------------------------------------------------------------
# Select / choice prompt
# ---------------------------------------------------------------------------

def ask_select(
    message: str,
    choices: list[str],
    default: Optional[str] = None,
) -> Optional[str]:
    """
    Present a list of options and ask the user to choose one.

    Args:
        message: The question to display.
        choices: List of option strings.
        default: The option pre-highlighted (must be in choices).

    Returns:
        The selected string, or None if cancelled.
    """
    try:
        return questionary.select(
            message,
            choices=choices,
            default=default,
            style=PROMPT_STYLE,
        ).ask()
    except (KeyboardInterrupt, EOFError):
        return None


# ---------------------------------------------------------------------------
# Checkbox (multi-select)
# ---------------------------------------------------------------------------

def ask_checkbox(
    message: str,
    choices: list[str],
    default: Optional[list[str]] = None,
) -> Optional[list[str]]:
    """
    Present a list where the user can select multiple items.

    Args:
        message: The question to display.
        choices: List of option strings.
        default: List of options pre-checked.

    Returns:
        List of selected strings, or None if cancelled.
    """
    try:
        return questionary.checkbox(
            message,
            choices=choices,
            default=default or [],
            style=PROMPT_STYLE,
        ).ask()
    except (KeyboardInterrupt, EOFError):
        return None


# ---------------------------------------------------------------------------
# Validators — reusable validation functions for ask_text / ask_password
# ---------------------------------------------------------------------------

def not_empty(value: str) -> bool | str:
    """Reject blank inputs."""
    return True if value.strip() else "This field cannot be empty."


def valid_url(value: str) -> bool | str:
    """Accept strings that look like URLs (http/https/git/ssh)."""
    stripped = value.strip()
    if not stripped:
        return "URL cannot be empty."
    prefixes = ("http://", "https://", "git@", "ssh://")
    if not any(stripped.startswith(p) for p in prefixes):
        return "Must start with http://, https://, git@, or ssh://"
    return True


def valid_port(value: str) -> bool | str:
    """Accept integers in the valid port range 1024–65535."""
    try:
        port = int(value)
        if 1024 <= port <= 65535:
            return True
        return "Port must be between 1024 and 65535."
    except ValueError:
        return "Must be a number."
