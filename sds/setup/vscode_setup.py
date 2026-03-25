# =============================================================================
# sds/setup/vscode_setup.py — VSCode workspace setup
# =============================================================================
# This module writes the VSCode configuration files that integrate the
# CLI tool with the VSCode editor. The key output is .vscode/tasks.json,
# which defines tasks that let you start/stop/restart Streamlit directly
# from the VSCode terminal panel or Command Palette.
#
# Files written:
#   .vscode/tasks.json        — Streamlit start/stop/restart tasks
#   .vscode/extensions.json   — Recommended extensions for this workspace
#   .vscode/settings.json     — Workspace settings (Python interpreter, etc.)
#
# This module does NOT start the tunnel or configure auth — those are
# handled by sds/tunnel/manager.py and sds/auth/microsoft.py respectively.
# =============================================================================

import json
from pathlib import Path

from sds.config import PROJECT_ROOT, cfg
from sds.ui.console import print_info, print_success, print_warning

# The .vscode directory lives at the project root.
VSCODE_DIR = PROJECT_ROOT / ".vscode"


def write_vscode_tasks() -> None:
    """
    Write .vscode/tasks.json with Streamlit management tasks.

    Creates the .vscode directory if it doesn't exist.
    Overwrites any existing tasks.json — it's always regenerated from config.
    """
    VSCODE_DIR.mkdir(parents=True, exist_ok=True)

    tasks = {
        # VSCode tasks format version — always "2.0.0" for modern VS Code.
        "version": "2.0.0",
        "tasks": [
            # ---------------------------------------------------------------
            # Task: Start Streamlit
            # Runs `python main.py streamlit start` in the integrated terminal.
            # ---------------------------------------------------------------
            {
                "label": "Streamlit: Start",
                "type": "shell",
                "command": f"python {PROJECT_ROOT / 'main.py'} streamlit start",
                "group": {
                    "kind": "build",
                    "isDefault": True,   # Ctrl+Shift+B runs this task.
                },
                "presentation": {
                    "reveal": "always",
                    "panel": "dedicated",    # Opens in its own terminal panel.
                    "clear": True,
                },
                "problemMatcher": [],       # No compiler output parsing needed.
            },

            # ---------------------------------------------------------------
            # Task: Stop Streamlit
            # ---------------------------------------------------------------
            {
                "label": "Streamlit: Stop",
                "type": "shell",
                "command": f"python {PROJECT_ROOT / 'main.py'} streamlit stop",
                "group": "build",
                "presentation": {
                    "reveal": "always",
                    "panel": "dedicated",
                    "clear": False,
                },
                "problemMatcher": [],
            },

            # ---------------------------------------------------------------
            # Task: Restart Streamlit
            # ---------------------------------------------------------------
            {
                "label": "Streamlit: Restart",
                "type": "shell",
                "command": f"python {PROJECT_ROOT / 'main.py'} streamlit restart",
                "group": "build",
                "presentation": {
                    "reveal": "always",
                    "panel": "dedicated",
                    "clear": True,
                },
                "problemMatcher": [],
            },

            # ---------------------------------------------------------------
            # Task: Attach to Streamlit logs
            # Opens a terminal pane streaming live Streamlit output.
            # ---------------------------------------------------------------
            {
                "label": "Streamlit: Attach (live logs)",
                "type": "shell",
                "command": f"python {PROJECT_ROOT / 'main.py'} attach",
                "group": "build",
                "presentation": {
                    "reveal": "always",
                    "panel": "dedicated",
                    "clear": True,
                },
                "problemMatcher": [],
                "runOptions": {
                    "runOn": "folderOpen",  # Auto-attach when workspace opens.
                },
            },

            # ---------------------------------------------------------------
            # Task: Full start (tunnel + Streamlit)
            # ---------------------------------------------------------------
            {
                "label": "Dev Machine: Start All",
                "type": "shell",
                "command": f"python {PROJECT_ROOT / 'main.py'} start",
                "group": "build",
                "presentation": {
                    "reveal": "always",
                    "panel": "dedicated",
                    "clear": True,
                },
                "problemMatcher": [],
            },

            # ---------------------------------------------------------------
            # Task: Full stop
            # ---------------------------------------------------------------
            {
                "label": "Dev Machine: Stop All",
                "type": "shell",
                "command": f"python {PROJECT_ROOT / 'main.py'} stop",
                "group": "build",
                "presentation": {
                    "reveal": "always",
                    "panel": "dedicated",
                    "clear": False,
                },
                "problemMatcher": [],
            },
        ],
    }

    tasks_path = VSCODE_DIR / "tasks.json"
    tasks_path.write_text(json.dumps(tasks, indent=4) + "\n")
    print_success(f"Wrote {tasks_path}")


def write_vscode_extensions() -> None:
    """
    Write .vscode/extensions.json with recommended extensions.

    These show up in the Extensions panel under "Workspace Recommendations".
    VSCode asks the user to install them when they first open the workspace.
    """
    extensions = {
        "recommendations": [
            "ms-python.python",                   # Python language support
            "ms-python.pylance",                  # Python type checking
            "ms-python.debugpy",                  # Python debugger
            "ms-toolsai.jupyter",                 # Jupyter notebook support
            "charliermarsh.ruff",                 # Fast Python linter
            "ms-vscode-remote.remote-tunnels",    # Remote tunnels UI
            "eamodio.gitlens",                    # Git history/blame overlays
            "mechatroner.rainbow-csv",            # CSV file viewer
            "redhat.vscode-yaml",                 # YAML support
        ]
    }

    extensions_path = VSCODE_DIR / "extensions.json"
    extensions_path.write_text(json.dumps(extensions, indent=4) + "\n")
    print_success(f"Wrote {extensions_path}")


def write_vscode_settings() -> None:
    """
    Write .vscode/settings.json with workspace-specific settings.

    These settings are workspace-scoped (not global) so they don't pollute
    the user's global VSCode config. They are git-ignored (see .gitignore).
    """
    import sys

    settings = {
        # Use the same Python interpreter that is running this script.
        "python.defaultInterpreterPath": sys.executable,

        # Format on save with Ruff (if extension is installed).
        "editor.formatOnSave": True,
        "[python]": {
            "editor.defaultFormatter": "charliermarsh.ruff",
        },

        # Show the terminal at the bottom by default.
        "terminal.integrated.defaultProfile.osx": "zsh",
        "terminal.integrated.defaultProfile.linux": "bash",

        # Streamlit files are Python — ensure syntax highlighting works.
        "files.associations": {
            "*.py": "python",
        },

        # Exclude runtime / generated dirs from file explorer.
        "files.exclude": {
            "**/__pycache__": True,
            "**/*.pyc": True,
            "**/.env": True,
            "**/logs": True,
            "**/.streamlit.pid": True,
            "**/.tunnel.pid": True,
            "**/.streamlit.sock": True,
        },
    }

    settings_path = VSCODE_DIR / "settings.json"
    settings_path.write_text(json.dumps(settings, indent=4) + "\n")
    print_success(f"Wrote {settings_path}")


def setup_vscode() -> None:
    """
    Run all VSCode setup steps in the correct order.
    Called by the setup pipeline after onboarding.
    """
    write_vscode_tasks()
    write_vscode_extensions()
    write_vscode_settings()
