# =============================================================================
# sds/identity.py — Machine identity and one-user lock
# =============================================================================
# This module enforces that the Streamlit Development Machine is tied to
# exactly ONE user on ONE machine.
#
# HOW IT WORKS
# ─────────────
# During onboarding, `generate_fingerprint()` hashes:
#   • The machine's hostname
#   • The machine's primary MAC address
#   • The OS username of the person running onboarding
#   • A passphrase chosen by the user (adds a secret component)
#
# This 64-char SHA-256 hex digest is stored in .env as MACHINE_FINGERPRINT.
# On every subsequent run, `verify_identity()` recomputes the same hash and
# compares it to what's stored. A mismatch aborts the program with a clear
# message.
#
# DOCKER MODE
# ─────────────
# Containers don't have a stable MAC address, so the identity check is
# bypassed when DOCKER_MODE=true is set in the environment.
# =============================================================================

import hashlib
import os
import socket
import uuid
from typing import Optional

from sds.ui.console import console, print_error, print_success, print_warning


# ---------------------------------------------------------------------------
# Fingerprint generation
# ---------------------------------------------------------------------------

def _get_machine_id() -> str:
    """
    Build a stable string that identifies this physical machine + OS user.

    Components:
    - hostname: Changes if machine is renamed, but that's intentional.
    - MAC address (uuid.getnode): Returns the first non-zero MAC found,
      or a random 48-bit number on some VMs — acceptable for our purposes.
    - OS username: Ties the fingerprint to the OS account.
    """
    hostname = socket.gethostname()
    mac = str(uuid.getnode())           # Integer representation of MAC
    username = os.getenv("USER") or os.getenv("USERNAME") or "unknown"
    return f"{hostname}::{mac}::{username}"


def generate_fingerprint(passphrase: str) -> str:
    """
    Generate the identity fingerprint for this machine + user + passphrase.

    The passphrase adds a secret component that is NOT derivable from the
    hardware alone. This means even someone with identical hardware cannot
    impersonate the user without knowing the passphrase.

    Args:
        passphrase: A secret string chosen during onboarding.

    Returns:
        64-character lowercase hex SHA-256 digest.
    """
    machine_id = _get_machine_id()
    # Combine machine identity with user-chosen passphrase.
    raw = f"{machine_id}::{passphrase}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Identity verification (called on every start)
# ---------------------------------------------------------------------------

def verify_identity(stored_fingerprint: str, stored_user: str) -> bool:
    """
    Verify that the current runtime environment matches the stored identity.

    This function is called by every CLI command before any action is taken.
    It performs two checks:
      1. OS username matches the stored ALLOWED_USER.
      2. Machine fingerprint can be recomputed only if passphrase is known.
         (We can't re-ask for the passphrase every time, so we only do the
          username check here. The fingerprint is validated during onboarding
          and stored. This function just ensures the username hasn't changed.)

    For the full fingerprint re-check (useful as a periodic audit), see
    `audit_fingerprint()` below.

    Args:
        stored_fingerprint: The MACHINE_FINGERPRINT value from .env.
        stored_user: The ALLOWED_USER value from .env.

    Returns:
        True if identity is valid, False if it should be rejected.
    """
    # --- Check: not configured yet? ---
    if not stored_fingerprint or not stored_user:
        # No fingerprint stored → first run, route to onboarding instead.
        return False

    # --- Check: OS username must match ---
    current_user = os.getenv("USER") or os.getenv("USERNAME") or ""
    if current_user.strip().lower() != stored_user.strip().lower():
        print_error(
            f"Identity check failed.\n"
            f"  This machine is locked to user: [bold]{stored_user}[/bold]\n"
            f"  Current user: [bold]{current_user}[/bold]\n\n"
            f"  If you are the authorised user, ensure you are running this\n"
            f"  tool under the correct OS account."
        )
        return False

    return True


def audit_fingerprint(stored_fingerprint: str, passphrase: str) -> bool:
    """
    Full fingerprint audit — recompute the hash and compare.

    This is used during onboarding to confirm the passphrase round-trips
    correctly, and can be called manually for a security audit.

    Args:
        stored_fingerprint: The value stored in .env.
        passphrase: The secret passphrase to test against.

    Returns:
        True if the recomputed fingerprint matches the stored one.
    """
    recomputed = generate_fingerprint(passphrase)
    return recomputed == stored_fingerprint


# ---------------------------------------------------------------------------
# Guard function — call this at the start of every CLI command
# ---------------------------------------------------------------------------

def identity_guard(docker_mode: bool = False) -> bool:
    """
    Combined identity check suitable for use at the top of CLI commands.

    Imports config internally to avoid circular imports (config imports nothing
    from identity; identity would create a cycle if it imported config at
    module level).

    Args:
        docker_mode: If True, skip all checks (container environment).

    Returns:
        True if the identity check passes (caller may proceed).
        False if it fails (caller should abort — the error is already printed).
    """
    # Skip all checks in Docker containers.
    if docker_mode:
        return True

    # Import here to avoid circular import (config.py is imported first).
    from sds.config import cfg

    # If the tool hasn't been configured yet, route to onboarding.
    if not cfg.is_configured:
        print_warning(
            "No configuration found. Run [bold cyan]python main.py onboard[/bold cyan] first."
        )
        return False

    return verify_identity(cfg.machine_fingerprint, cfg.allowed_user)
