# =============================================================================
# sds/onboarding/steps.py — Individual onboarding wizard steps
# =============================================================================
# Each function in this module represents one step of the onboarding wizard.
# Steps are called in sequence by onboarding/wizard.py.
#
# Each step function:
#   1. Displays a Rich header explaining what it's collecting.
#   2. Uses questionary prompts (via sds/ui/prompts.py) to gather input.
#   3. Returns a dict of {ENV_VAR_NAME: value} to be written to .env.
#   4. Returns None if the user cancels (wizard aborts).
#
# Keeping steps in a separate module makes each one independently readable
# and testable without touching the wizard orchestrator.
# =============================================================================

import os
from typing import Optional

from sds.ui.console import console, print_header, print_info, print_rule
from sds.ui.prompts import (
    ask_confirm,
    ask_password,
    ask_select,
    ask_text,
    not_empty,
    valid_url,
    valid_port,
)


# ---------------------------------------------------------------------------
# Step 1 — Identity / user lock
# ---------------------------------------------------------------------------

def step_identity() -> Optional[dict]:
    """
    Collect the user's identity information and generate the machine lock.

    This step ties the installation to ONE specific user by:
    - Recording the current OS username as ALLOWED_USER.
    - Asking for a secret passphrase.
    - Computing a SHA-256 fingerprint from machine + username + passphrase.
    - Storing the fingerprint in .env as MACHINE_FINGERPRINT.

    Returns:
        Dict with ALLOWED_USER, MACHINE_FINGERPRINT keys, or None on cancel.
    """
    print_header(
        "Step 1/5 — Identity Lock",
        "This installation will be locked to your OS user on this machine.",
    )

    console.print(
        "  [dim]The identity fingerprint prevents anyone else from using this tool.\n"
        "  It combines your hostname, MAC address, OS username, and a passphrase.[/dim]\n"
    )

    # The ALLOWED_USER is the current OS username — not user-editable.
    current_user = os.getenv("USER") or os.getenv("USERNAME") or ""
    if not current_user:
        console.print("[bold red]Cannot determine OS username. Aborting.[/bold red]")
        return None

    console.print(f"  Detected OS user: [bold cyan]{current_user}[/bold cyan]\n")

    confirmed = ask_confirm(f"Lock this installation to '{current_user}'?", default=True)
    if not confirmed:
        return None

    # Ask for passphrase — used in fingerprint hash, never stored in plain text.
    console.print(
        "\n  [dim]Choose a passphrase. This is NOT a system password — it's a secret\n"
        "  component baked into the identity fingerprint. You'll need it if you\n"
        "  ever want to audit or reset the lock.[/dim]\n"
    )
    passphrase = ask_password(
        "Identity passphrase",
        validate=lambda v: "Passphrase cannot be empty." if not v.strip() else True,
    )
    if passphrase is None:
        return None

    passphrase_confirm = ask_password("Confirm passphrase")
    if passphrase_confirm != passphrase:
        console.print("[bold red]Passphrases do not match. Try again.[/bold red]")
        return None

    # Generate fingerprint (imported here to avoid circular at module load).
    from sds.identity import generate_fingerprint
    fingerprint = generate_fingerprint(passphrase)

    console.print(f"\n  [dim]Fingerprint: {fingerprint[:16]}...{fingerprint[-8:]}[/dim]")

    return {
        "ALLOWED_USER": current_user,
        "MACHINE_FINGERPRINT": fingerprint,
    }


# ---------------------------------------------------------------------------
# Step 2 — Git configuration
# ---------------------------------------------------------------------------

def step_git() -> Optional[dict]:
    """
    Collect git credentials and repository URL.

    This step sets up:
    - git user.name and user.email (for commits)
    - A GitHub Personal Access Token (for clone/pull over HTTPS)
    - The repository URL to clone
    - The branch to track

    Returns:
        Dict with GIT_* keys, or None on cancel.
    """
    print_header(
        "Step 2/5 — Git Configuration",
        "Set up git credentials and the repository to work with.",
    )

    git_username = ask_text(
        "Your name (for git commits)",
        validate=not_empty,
    )
    if git_username is None:
        return None

    git_email = ask_text(
        "Your email (for git commits)",
        validate=not_empty,
    )
    if git_email is None:
        return None

    console.print(
        "\n  [dim]A GitHub Personal Access Token is needed to clone private repos.\n"
        "  Generate one at: github.com → Settings → Developer settings → PAT.\n"
        "  Required scope: repo (read)[/dim]\n"
    )

    git_token = ask_password("GitHub Personal Access Token (leave blank for public repos)")
    if git_token is None:
        return None

    git_repo_url = ask_text(
        "Repository URL (HTTPS or SSH)",
        validate=valid_url,
    )
    if git_repo_url is None:
        return None

    git_branch = ask_text("Branch to track", default="main")
    if git_branch is None:
        return None

    return {
        "GIT_USERNAME": git_username,
        "GIT_EMAIL": git_email,
        "GIT_TOKEN": git_token,
        "GIT_REPO_URL": git_repo_url,
        "GIT_BRANCH": git_branch,
        "REPO_FOLDER": "./repo",
    }


# ---------------------------------------------------------------------------
# Step 3 — Streamlit configuration
# ---------------------------------------------------------------------------

def step_streamlit() -> Optional[dict]:
    """
    Collect Streamlit development server settings.

    Returns:
        Dict with STREAMLIT_* keys, or None on cancel.
    """
    print_header(
        "Step 3/5 — Streamlit Dev Server",
        "Configure which file to run and which port to serve on.",
    )

    console.print(
        "  [dim]This is the Python file inside your repo that Streamlit will run.\n"
        "  It must be relative to the repo root (e.g. litdev.py or app/main.py).[/dim]\n"
    )

    dev_file = ask_text(
        "Streamlit entry file (relative to repo root)",
        default="litdev.py",
        validate=not_empty,
    )
    if dev_file is None:
        return None

    port_str = ask_text(
        "Streamlit port",
        default="8501",
        validate=valid_port,
    )
    if port_str is None:
        return None

    return {
        "STREAMLIT_DEV_FILE": dev_file,
        "STREAMLIT_PORT": port_str,
        "STREAMLIT_HOST": "0.0.0.0",
    }


# ---------------------------------------------------------------------------
# Step 4 — VSCode Tunnel
# ---------------------------------------------------------------------------

def step_vscode_tunnel() -> Optional[dict]:
    """
    Collect VSCode tunnel configuration.

    The tunnel name must be unique across the user's Microsoft account.
    It appears as the machine name in vscode.dev.

    Returns:
        Dict with VSCODE_TUNNEL_NAME, or None on cancel.
    """
    print_header(
        "Step 4/5 — VSCode Tunnel",
        "Configure the remote VSCode web tunnel name.",
    )

    console.print(
        "  [dim]The tunnel name is how this machine appears on vscode.dev.\n"
        "  Use lowercase letters, numbers, and hyphens only.\n"
        "  Example: my-streamlit-box[/dim]\n"
    )

    tunnel_name = ask_text(
        "Tunnel name",
        default="streamlit-dev-machine",
        validate=not_empty,
    )
    if tunnel_name is None:
        return None

    return {
        "VSCODE_TUNNEL_NAME": tunnel_name,
    }


# ---------------------------------------------------------------------------
# Step 5 — Microsoft Authentication app registration
# ---------------------------------------------------------------------------

def step_microsoft_auth() -> Optional[dict]:
    """
    Collect Microsoft Azure app registration details for device-flow OAuth.

    The actual authentication (device code flow) happens at runtime when the
    tunnel starts. This step just records the client/tenant IDs.

    Returns:
        Dict with MS_CLIENT_ID, MS_TENANT_ID, or None on cancel.
    """
    print_header(
        "Step 5/5 — Microsoft Authentication",
        "App registration details for VSCode tunnel login.",
    )

    console.print(
        "  [dim]VSCode tunnel uses Microsoft OAuth for authentication.\n"
        "  You can use the default Microsoft VSCode client ID, or your own\n"
        "  Azure app registration if you have one.[/dim]\n"
    )

    use_default = ask_confirm(
        "Use the default VSCode Microsoft app registration?",
        default=True,
    )
    if use_default is None:
        return None

    if use_default:
        # The well-known client ID used by the VS Code CLI for device flow.
        # This is publicly documented and is safe to embed.
        ms_client_id = "aebc6443-996d-45c2-90f0-388ff96faa56"
        ms_tenant_id = "common"
        console.print(f"  [dim]Using default client ID: {ms_client_id}[/dim]")
    else:
        ms_client_id = ask_text(
            "Azure App Client ID",
            validate=not_empty,
        )
        if ms_client_id is None:
            return None

        ms_tenant_id = ask_text(
            "Azure Tenant ID (use 'common' for multi-tenant)",
            default="common",
            validate=not_empty,
        )
        if ms_tenant_id is None:
            return None

    return {
        "MS_CLIENT_ID": ms_client_id,
        "MS_TENANT_ID": ms_tenant_id,
    }
