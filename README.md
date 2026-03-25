# Streamlit Development Machine

An automated Python CLI that turns a bare machine into a fully configured
Streamlit development environment — with a VSCode web tunnel, a managed
single-instance dev server, Microsoft authentication, and a one-user identity
lock. Everything is driven from the terminal; no GUI required.

---

## What It Does

Two core objectives:

1. **Serve VSCode on the web** via `code tunnel` — access your full editor at
   `https://vscode.dev/tunnel/<your-name>` from any browser.
2. **Serve a Streamlit dev server** from a file in your cloned repo, managed
   as a single-instance background process with live log streaming.

---

## Workflow

```
Machine On
  └── python main.py start
        1. Verify identity fingerprint (one-user lock)
        2. Check / install system dependencies
        3. Git: configure + clone / pull repo
        4. Microsoft auth: device code flow (interactive CLI)
        5. VSCode tunnel: start code tunnel
        6. Streamlit: start dev server (litdev.py by default)
        7. Print live status dashboard
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the onboarding wizard (first time only — sets up .env and all config)
python main.py onboard

# 3. Start everything (tunnel + Streamlit)
python main.py start

# 4. Stream live Streamlit logs in a separate terminal
python main.py attach

# 5. Stop everything
python main.py stop
```

---

## CLI Reference

```bash
python main.py onboard              # First-run setup wizard (5 steps)
python main.py start                # Start tunnel + Streamlit
python main.py stop                 # Stop tunnel + Streamlit
python main.py status               # Show status table of all services
python main.py attach               # Stream live Streamlit logs (Ctrl+C to detach)

python main.py tunnel start         # Start VSCode tunnel only
python main.py tunnel stop          # Stop VSCode tunnel only
python main.py tunnel login         # Re-authenticate Microsoft account
python main.py tunnel status        # Show tunnel status

python main.py streamlit start      # Start Streamlit only
python main.py streamlit stop       # Stop Streamlit only
python main.py streamlit restart    # Restart Streamlit
python main.py streamlit status     # Show Streamlit status

python main.py --help               # Full command reference
```

---

## Onboarding Wizard

The wizard runs automatically on first use (`python main.py onboard`). It walks
through 5 interactive steps:

| Step | What it collects |
|------|-----------------|
| 1. Identity lock | OS username + passphrase → generates SHA-256 fingerprint |
| 2. Git | username, email, GitHub token, repo URL, branch |
| 3. Streamlit | entry file (`litdev.py`), port, host |
| 4. VSCode tunnel | tunnel name (shown on vscode.dev) |
| 5. Microsoft auth | Azure client ID + tenant ID |

After the wizard, it automatically installs dependencies, configures git, clones
the repo, and writes `.vscode/tasks.json`.

---

## Configuration

All settings live in `.env` (git-ignored, written by the wizard).
Copy `.env.template` to see every available variable.

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `STREAMLIT_DEV_FILE` | `litdev.py` | File inside repo to run with Streamlit |
| `STREAMLIT_PORT` | `8501` | Local port for the dev server |
| `GIT_REPO_URL` | — | Repository to clone |
| `GIT_TOKEN` | — | GitHub Personal Access Token |
| `VSCODE_TUNNEL_NAME` | `streamlit-dev-machine` | Name on vscode.dev |
| `MS_CLIENT_ID` | VSCode default | Azure app client ID |
| `MACHINE_FINGERPRINT` | auto-generated | SHA-256 identity lock hash |
| `ALLOWED_USER` | auto-detected | OS username allowed to run this tool |
| `DOCKER_MODE` | `false` | Set `true` to bypass identity check in containers |

---

## Key Design Decisions

| Feature | How it works |
|---------|-------------|
| **One-user lock** | SHA-256 of `hostname + MAC + username + passphrase` stored in `.env`. Every command verifies before proceeding. |
| **Single Streamlit instance** | PID file + `psutil` liveness check. `start()` refuses if a live process is found at the stored PID. |
| **Attach / live logs** | Unix socket IPC — the daemon streams log lines to a buffer; `attach` connects as a client and receives them in real time. VSCode tasks can also send `stop`/`restart` commands through the same socket. |
| **VSCode control** | `.vscode/tasks.json` tasks call `python main.py streamlit start/stop` — works from any process, including Docker. |
| **MS auth** | Device code flow — prints a URL and short code to the terminal, polls the token endpoint silently. No browser automation; entirely interactive CLI. |
| **Docker mode** | `DOCKER_MODE=true` bypasses the fingerprint check; `docker/start.py` skips onboarding and reads all config from environment variables. |

---

## VSCode Tasks

Once onboarded, the following tasks are available in VSCode
(`Ctrl+Shift+P` → `Tasks: Run Task`):

| Task | Action |
|------|--------|
| `Streamlit: Start` | Start the dev server (also bound to `Ctrl+Shift+B`) |
| `Streamlit: Stop` | Stop the dev server |
| `Streamlit: Restart` | Stop + start |
| `Streamlit: Attach (live logs)` | Open a terminal streaming live output |
| `Dev Machine: Start All` | Start tunnel + Streamlit |
| `Dev Machine: Stop All` | Stop tunnel + Streamlit |
| `Dev Machine: Status` | Show status dashboard |

---

## Docker

```bash
# Build
docker build -f docker/Dockerfile -t streamlit-dev-machine .

# Run
docker run -it \
  -e GIT_REPO_URL=https://github.com/user/repo \
  -e GIT_TOKEN=ghp_... \
  -e STREAMLIT_DEV_FILE=litdev.py \
  -p 8501:8501 \
  streamlit-dev-machine
```

The container clones the repo, installs dependencies, and starts Streamlit.
The identity lock is bypassed in Docker mode (`DOCKER_MODE=true`).
Secrets are never baked into the image — always inject via `-e` flags.

---

## File Layout (27 files)

```
main.py                          ← Entry point: python main.py <cmd>
requirements.txt                 ← Pinned deps (typer, rich, questionary, etc.)
.env.template                    ← Config template (copy to .env, filled by wizard)
.gitignore
CLAUDE.md                        ← Project tracking doc

sds/                             ← Main package ("Streamlit Dev Server")
  config.py                      ← Loads .env, exposes typed `cfg` singleton
  identity.py                    ← One-user fingerprint lock (SHA-256)
  cli.py                         ← Typer commands dispatch layer
  ui/console.py                  ← Rich output helpers (banner, tables, etc.)
  ui/prompts.py                  ← Questionary wrappers (text/password/confirm)
  onboarding/wizard.py           ← 5-step first-run wizard orchestrator
  onboarding/steps.py            ← Each wizard step as a separate function
  setup/deps.py                  ← pip install + git + VSCode CLI installer
  setup/git_setup.py             ← git config, clone, pull (GitPython)
  setup/vscode_setup.py          ← Writes .vscode/tasks.json + settings
  auth/microsoft.py              ← Device-flow OAuth (interactive CLI only)
  tunnel/manager.py              ← code tunnel start/stop/status
  streamlit/daemon.py            ← Single-instance Streamlit process manager
  streamlit/ipc.py               ← Unix socket IPC (server + client for attach)

docker/Dockerfile                ← Multi-stage build (builder + slim runtime)
docker/start.py                  ← Container entrypoint (bypasses onboarding)
.vscode/tasks.json               ← VSCode tasks: start/stop/restart/attach
logs/.gitkeep
```

---

## Requirements

- Python 3.10+
- macOS or Linux (Windows not supported — Unix socket IPC dependency)
- Internet access for first-run installs and Microsoft auth
- A GitHub account (for git operations)
- A Microsoft account (for VSCode tunnel authentication)

---

## Runtime Files (git-ignored)

These are created at runtime and should never be committed:

| File | Purpose |
|------|---------|
| `.env` | Live config, written by onboarding |
| `.streamlit.pid` | PID of the running Streamlit process |
| `.tunnel.pid` | PID of the running `code tunnel` process |
| `.streamlit.sock` | Unix socket for IPC log streaming |
| `logs/streamlit.log` | Captured stdout/stderr from Streamlit |
