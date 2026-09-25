#!/usr/bin/env python3
# =============================================================================
# main.py — Entry point for the Streamlit Development Machine CLI
# =============================================================================
# This is the only file you need to call directly:
#
#   python main.py onboard         ← Run once on a new machine
#   python main.py start           ← Start tunnel + Streamlit
#   python main.py status          ← Check what's running
#   python main.py attach          ← Stream Streamlit live logs
#   python main.py stop            ← Stop everything
#   python main.py --help          ← Full command reference
#
# This file is intentionally thin. All logic lives in the sds/ package.
# We just import the Typer app and run it. Keeping main.py minimal means
# the sds package can also be imported as a library if needed.
# =============================================================================

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is on the Python path.
# This allows running `python main.py` from any directory.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Import and run the Typer application.
# ---------------------------------------------------------------------------
try:
    from sds.cli import app
except ModuleNotFoundError as exc:
    if exc.name in {"typer", "rich", "questionary", "dotenv", "psutil", "requests", "git"}:
        print(
            "Missing required dependencies.\n"
            "Install them with:\n"
            "  python -m pip install -r requirements.txt"
        )
        raise SystemExit(1) from exc
    raise

if __name__ == "__main__":
    app()
