# =============================================================================
# sds/auth/microsoft.py — Microsoft OAuth 2.0 Device Code Flow
# =============================================================================
# This module authenticates the user with Microsoft's identity platform using
# the Device Authorization Grant (RFC 8628). This flow is designed for CLI
# tools — it never opens a browser programmatically. Instead, it prints a
# URL and a short code to the terminal and tells the user to visit it.
#
# HOW THE FLOW WORKS
# ──────────────────
# 1. We POST to /devicecode to get a device_code + user_code + verification_uri.
# 2. We print the user_code and verification_uri to the terminal (via Rich).
# 3. We poll /token every `interval` seconds.
# 4. When the user approves on the web, the poll returns an access_token +
#    refresh_token. We store these in .env.
# 5. On future runs, `ensure_authenticated()` checks the token expiry and
#    refreshes automatically if needed.
#
# SCOPES
# ──────
# For VSCode tunnel login we request the scopes needed by the `code tunnel`
# command. If you're using your own Azure app, ensure these scopes are
# granted in the app registration.
# =============================================================================

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from sds.config import cfg, write_env
from sds.ui.console import console, print_info, print_success, print_error, print_warning
from rich.panel import Panel

# ---------------------------------------------------------------------------
# Microsoft identity platform endpoints
# ---------------------------------------------------------------------------
# {tenant} is replaced at runtime with cfg.ms_tenant_id ("common" for multi-tenant).
DEVICE_CODE_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode"
TOKEN_URL       = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

# Scopes required for VSCode tunnel authentication.
# offline_access is needed to receive a refresh_token.
SCOPES = " ".join([
    "https://management.core.windows.net//.default",
    "offline_access",
])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ensure_authenticated() -> bool:
    """
    Ensure we have a valid, non-expired Microsoft access token.

    - If a valid token is stored in .env → return True immediately.
    - If the token is expired but a refresh token exists → refresh silently.
    - If no token at all → run the full device code flow (interactive).

    Returns:
        True if we now have a valid token, False on failure.
    """
    if not cfg.ms_client_id:
        print_warning(
            "MS_CLIENT_ID not configured. Skipping Microsoft authentication.\n"
            "  Run [bold cyan]python main.py onboard[/bold cyan] to configure."
        )
        return False

    if _token_is_valid():
        print_info("Microsoft auth — token valid, skipping login.")
        return True

    if cfg.ms_refresh_token:
        print_info("Microsoft auth — refreshing expired token ...")
        if _refresh_token():
            return True
        print_warning("Token refresh failed. Falling back to full login.")

    # Full interactive device flow.
    return login()


def login() -> bool:
    """
    Run the full interactive Microsoft device code flow.

    This is intentionally interactive — it prints the user code to the
    terminal and waits for the user to complete auth in a browser.
    No browser is opened by this code.

    Returns:
        True on successful login, False on error or timeout.
    """
    tenant = cfg.ms_tenant_id or "common"
    client_id = cfg.ms_client_id

    if not client_id:
        print_error("MS_CLIENT_ID is not configured. Cannot perform Microsoft login.")
        return False

    # Step 1 — Request a device code.
    try:
        resp = requests.post(
            DEVICE_CODE_URL.format(tenant=tenant),
            data={
                "client_id": client_id,
                "scope": SCOPES,
            },
            timeout=10,
        )
        resp.raise_for_status()
        device_data = resp.json()
    except requests.RequestException as exc:
        print_error(f"Failed to request device code: {exc}")
        return False

    user_code        = device_data.get("user_code", "")
    verification_uri = device_data.get("verification_uri", "")
    device_code      = device_data.get("device_code", "")
    expires_in       = int(device_data.get("expires_in", 900))      # seconds
    interval         = int(device_data.get("interval", 5))           # polling interval

    # Step 2 — Show the code to the user.
    _print_device_code_prompt(user_code, verification_uri, expires_in)

    # Step 3 — Poll for completion.
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)

        try:
            token_resp = requests.post(
                TOKEN_URL.format(tenant=tenant),
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": client_id,
                    "device_code": device_code,
                },
                timeout=10,
            )
            token_data = token_resp.json()
        except requests.RequestException as exc:
            print_warning(f"Poll request failed (will retry): {exc}")
            continue

        error = token_data.get("error", "")

        if error == "authorization_pending":
            # Normal — user hasn't finished auth yet. Keep polling.
            print(".", end="", flush=True)
            continue

        if error == "slow_down":
            # Server asking us to back off.
            interval += 5
            continue

        if error == "authorization_declined":
            print()
            print_error("Authentication was declined by the user.")
            return False

        if error == "expired_token":
            print()
            print_error("The device code expired. Run login again.")
            return False

        if error:
            print()
            print_error(f"Unexpected auth error: {error} — {token_data.get('error_description', '')}")
            return False

        # Success — we received tokens.
        print()  # newline after the dots
        _store_tokens(token_data)
        print_success("Microsoft authentication successful.")
        return True

    print()
    print_error("Device code flow timed out. Run login again.")
    return False


def logout() -> None:
    """
    Clear stored Microsoft tokens from .env.

    Does not revoke the token server-side (would require an additional request).
    After logout, `ensure_authenticated()` will prompt for login again.
    """
    write_env({
        "MS_ACCESS_TOKEN": "",
        "MS_REFRESH_TOKEN": "",
        "MS_TOKEN_EXPIRY": "",
    })
    print_success("Microsoft tokens cleared. You will be prompted to log in next time.")


def is_authenticated() -> bool:
    """Return True if a valid (non-expired) access token is stored."""
    return _token_is_valid()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _token_is_valid() -> bool:
    """Check whether the stored access token exists and has not expired."""
    token = cfg.ms_access_token
    expiry_str = cfg.ms_token_expiry

    if not token or not expiry_str:
        return False

    try:
        expiry = datetime.fromisoformat(expiry_str)
        # Consider the token expired 60 seconds before the actual expiry
        # to avoid using a token that expires mid-request.
        return datetime.now(timezone.utc) < (expiry - timedelta(seconds=60))
    except (ValueError, TypeError):
        return False


def _refresh_token() -> bool:
    """
    Use the stored refresh token to get a new access token silently.

    Returns True if refresh succeeded and new tokens were stored.
    """
    tenant = cfg.ms_tenant_id or "common"

    try:
        resp = requests.post(
            TOKEN_URL.format(tenant=tenant),
            data={
                "grant_type": "refresh_token",
                "client_id": cfg.ms_client_id,
                "refresh_token": cfg.ms_refresh_token,
                "scope": SCOPES,
            },
            timeout=10,
        )
        resp.raise_for_status()
        token_data = resp.json()
    except requests.RequestException as exc:
        print_warning(f"Token refresh request failed: {exc}")
        return False

    if "access_token" not in token_data:
        print_warning(f"Refresh response did not include access_token: {token_data.get('error', 'unknown')}")
        return False

    _store_tokens(token_data)
    print_success("Microsoft token refreshed.")
    return True


def _store_tokens(token_data: dict) -> None:
    """
    Persist access_token, refresh_token, and computed expiry to .env.

    Args:
        token_data: The JSON dict returned by the /token endpoint.
    """
    access_token  = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in    = int(token_data.get("expires_in", 3600))

    expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    write_env({
        "MS_ACCESS_TOKEN":  access_token,
        "MS_REFRESH_TOKEN": refresh_token,
        "MS_TOKEN_EXPIRY":  expiry.isoformat(),
    })


def _print_device_code_prompt(user_code: str, uri: str, expires_in: int) -> None:
    """
    Print the device code authentication prompt using Rich.

    The user needs to:
      1. Open `uri` in a browser.
      2. Enter `user_code` when prompted.
      3. Approve the request.
    """
    minutes = expires_in // 60
    content = (
        f"  To sign in to your Microsoft account:\n\n"
        f"  1. Open this URL in your browser:\n"
        f"     [bold cyan underline]{uri}[/bold cyan underline]\n\n"
        f"  2. Enter this code:\n"
        f"     [bold white on blue]  {user_code}  [/bold white on blue]\n\n"
        f"  [dim]Code expires in {minutes} minutes. Waiting for you to complete auth...[/dim]"
    )
    console.print(Panel(content, title="[bold]Microsoft Login Required[/bold]", border_style="blue"))
