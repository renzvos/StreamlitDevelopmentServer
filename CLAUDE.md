# Streamlit Development Machine — CLAUDE.md

> **Project Tracking File** — Updated each session to reflect current state,
> decisions made, known issues, and what to tackle next.

---

## What This Project Is

A self-contained, automated Python CLI that turns a bare machine into a
Streamlit development environment. It handles everything from dependency
installation to VSCode web tunnel to a managed, single-instance Streamlit
dev server — all via an interactive TUI running in the terminal.

**Locked to one user only.** An identity fingerprint is generated during
onboarding and stored in `.env`. Every subsequent run verifies the fingerprint
before proceeding. Mismatched machines or users are rejected at the gate.

---

## Key Goals

| # | Goal |
|---|---|
| 1 | Serve VSCode via a web tunnel (`code tunnel`) |
| 2 | Serve a Streamlit dev server from a repo file (`litdev.py` by default) |
| 3 | Enforce single Streamlit instance (PID file + Unix socket IPC) |
| 4 | Provide `attach` command to stream Streamlit logs live |
| 5 | VSCode tasks can start/stop Streamlit (`.vscode/tasks.json`) |

---

## Architecture

```
main.py  (entry point)
  └── sds/cli.py  (Typer command dispatch)
        ├── onboard    → sds/onboarding/wizard.py
        │                   → sds/identity.py        (fingerprint write)
        │                   → sds/setup/deps.py      (pip + system tools)
        │                   → sds/setup/git_setup.py (git config + clone)
        │                   └── sds/setup/vscode_setup.py
        │
        ├── start      → sds/auth/microsoft.py       (device-flow auth)
        │              → sds/tunnel/manager.py        (code tunnel)
        │              → sds/streamlit/daemon.py      (streamlit run)
        │
        ├── stop       → sds/streamlit/daemon.py
        │              → sds/tunnel/manager.py
        │
        ├── attach     → sds/streamlit/ipc.py  (Unix socket client)
        ├── status     → all managers (aggregate status table)
        ├── tunnel     → sds/tunnel/manager.py
        └── streamlit  → sds/streamlit/daemon.py
```

### Runtime files (git-ignored)

| File | Purpose |
|---|---|
| `.env` | Live config, written by onboarding |
| `.streamlit.pid` | PID of the running Streamlit process |
| `.tunnel.pid` | PID of the running `code tunnel` process |
| `.streamlit.sock` | Unix socket for IPC log streaming |
| `logs/streamlit.log` | Captured stdout/stderr from Streamlit |

---

## CLI Reference

```bash
python main.py onboard              # First-run setup wizard
python main.py start                # Start tunnel + Streamlit
python main.py stop                 # Stop tunnel + Streamlit
python main.py status               # Show status of all services
python main.py attach               # Stream live Streamlit logs
python main.py tunnel start         # Start VSCode tunnel only
python main.py tunnel stop          # Stop VSCode tunnel only
python main.py streamlit start      # Start Streamlit only
python main.py streamlit stop       # Stop Streamlit only
python main.py streamlit restart    # Restart Streamlit
```

---

## Workflow (Automated)

```
Machine On
  → python main.py start
      1. Load + validate .env config
      2. Verify identity fingerprint (one-user lock)
      3. Check/install system dependencies
      4. Git: configure + clone/pull repo
      5. Microsoft auth: device flow (interactive CLI)
      6. VSCode tunnel: start code tunnel
      7. Streamlit: start dev server from STREAMLIT_DEV_FILE
      8. Print live status dashboard
```

---

## Configuration (.env)

All values are set during onboarding. The template is `.env.template`.

Key variables:
- `STREAMLIT_DEV_FILE` — file to run (default: `litdev.py`)
- `GIT_REPO_URL` — repository to clone
- `GIT_USERNAME` / `GIT_TOKEN` — git credentials
- `VSCODE_TUNNEL_NAME` — tunnel name for `code tunnel`
- `MS_CLIENT_ID` / `MS_TENANT_ID` — Microsoft app registration
- `MACHINE_FINGERPRINT` — SHA-256 hash locking this install to one user
- `ALLOWED_USER` — OS username allowed to run this tool

---

## Package Layout

```
sds/
  cli.py              Command dispatch (Typer app)
  config.py           Config loader & validator
  identity.py         One-user fingerprint lock
  onboarding/
    wizard.py         First-run wizard orchestrator
    steps.py          Individual wizard steps (questionary prompts)
  setup/
    deps.py           System + Python dependency installer
    git_setup.py      Git config, clone, pull
    vscode_setup.py   Write .vscode/tasks.json
  auth/
    microsoft.py      Microsoft device-flow OAuth
  tunnel/
    manager.py        code tunnel process manager
  streamlit/
    daemon.py         Single-instance Streamlit process manager
    ipc.py            Unix socket IPC (server + client)
  ui/
    console.py        Shared Rich console + display helpers
    prompts.py        Questionary prompt wrappers
docker/
  Dockerfile          Container image definition
  start.py            Docker entrypoint (bypasses onboarding)
.vscode/
  tasks.json          VSCode tasks: Streamlit start/stop
```

---

## Session Log

| Date | What happened |
|---|---|
| 2026-03-25 | Initial scaffold: all files created, full architecture wired |

---

## Known Issues / Decisions

- **Docker mode**: Identity lock is bypassed when `DOCKER_MODE=true` is set.
  This is intentional — containers don't have a stable fingerprint.
- **Windows**: Not supported. The Unix socket IPC and `code tunnel` behavior
  differ on Windows. macOS/Linux only.
- **VSCode CLI**: The `code` binary must be the server CLI, not the desktop
  app. The installer downloads it from `code.visualstudio.com/sha/download`.
- **MS auth tokens**: Stored in `.env` as `MS_ACCESS_TOKEN` / `MS_REFRESH_TOKEN`.
  These are sensitive — ensure `.env` is never committed.
