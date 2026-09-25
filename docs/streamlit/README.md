# Streamlit Runtime Guide

This guide covers the Streamlit process managed by the CLI.

## Commands

```bash
python main.py streamlit start
python main.py streamlit stop
python main.py streamlit restart
python main.py streamlit status
python main.py attach
```

## How it works

- Entry file is read from `STREAMLIT_DEV_FILE` in `.env` (default: `litdev.py`).
- Only one instance is allowed at a time (PID-based guard).
- Logs are written to `logs/streamlit.log`.
- `attach` streams logs live over the Unix socket IPC channel.

## Common issues

- **Entry file not found**: ensure the configured file exists inside `REPO_FOLDER`.
- **Port conflict**: change `STREAMLIT_PORT` in `.env` and restart.
- **Stale PID/socket**: run `python main.py streamlit stop` then `start`.
