# =============================================================================
# Dockerfile — Streamlit Development Machine container image
# =============================================================================
# This image packages the entire dev machine environment for container use.
#
# USAGE
# ──────
# Build:
#   docker build -t streamlit-dev-machine .
#
# Run using the docker.env file (recommended):
#   docker run -it --env-file docker.env -p 8501:8501 streamlit-dev-machine
#
# GitHub authentication (for private repos) is handled interactively via
# `gh auth login` inside the container — no GIT_TOKEN needed.
# Public repos (like the default streamlit-example) need no auth at all.
#
# NOTE: The identity fingerprint check is BYPASSED in Docker mode
#       (DOCKER_MODE=true). All secrets are injected via `-e` flags
#       or a docker-compose.yml — never baked into the image.
#
# MULTI-STAGE BUILD
# ──────────────────
# Stage 1 (builder): Install Python dependencies into a virtual environment.
# Stage 2 (runtime): Copy only the venv and project files into a slim image.
# This keeps the final image small.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1 — Builder: install Python dependencies
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# Avoid interactive prompts during apt operations.
ENV DEBIAN_FRONTEND=noninteractive

# Install system build tools needed for some Python packages.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment in /opt/venv.
# Using a venv keeps the system Python clean and makes copying easy.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only requirements first (Docker layer cache: this layer only
# re-runs if requirements.txt changes, not on every code change).
WORKDIR /app
COPY requirements.txt .

# Install Python dependencies into the venv.
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ---------------------------------------------------------------------------
# Stage 2 — Runtime: slim final image
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV DEBIAN_FRONTEND=noninteractive

# Install runtime system dependencies.
# git       — for clone/pull at runtime.
# curl      — for healthcheck and downloads.
# tar       — for extracting the VSCode CLI archive.
# gh        — GitHub CLI for interactive authentication (no tokens needed).
#             Installed from the official GitHub CLI apt repo.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    tar \
    gnupg \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
       | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
       > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Install the VSCode Server CLI (`code tunnel`).
# Uses update.code.visualstudio.com/latest — the canonical stable endpoint.
# Architecture is detected at build time (amd64 → x64, arm64 → arm64).
# Binary is placed at /usr/local/bin/code and made executable.
RUN ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "arm64" ]; then \
         VS_ARCH="arm64"; \
       else \
         VS_ARCH="x64"; \
       fi \
    && curl -fsSL "https://update.code.visualstudio.com/latest/cli-linux-${VS_ARCH}/stable" \
       -o /tmp/vscode-cli.tar.gz \
    && tar -xzf /tmp/vscode-cli.tar.gz -C /usr/local/bin \
    && chmod +x /usr/local/bin/code \
    && rm /tmp/vscode-cli.tar.gz

# Copy the virtual environment from the builder stage.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set the working directory.
WORKDIR /app

# Copy the project source code.
# .dockerignore should exclude .env, .git, logs/, __pycache__, etc.
COPY . .

# ---------------------------------------------------------------------------
# Runtime environment variables with defaults.
# These match the variables in .env.template exactly.
# Override any of these at `docker run` time with -e VAR=value.
# Secrets (GIT_TOKEN, MS_ACCESS_TOKEN, etc.) must always be injected at
# runtime — never bake them into the image.
# ---------------------------------------------------------------------------

# --- Identity (skip lock in containers) ---
ENV DOCKER_MODE=true
ENV ALLOWED_USER=
ENV MACHINE_FINGERPRINT=

# --- Git ---
# Default repo: official public Streamlit example (no token required).
# Authentication is handled interactively via `gh auth login` at runtime.
# GIT_TOKEN is intentionally absent — use gh CLI instead.
ENV GIT_USERNAME=streamlit-dev
ENV GIT_EMAIL=dev@example.com
ENV GIT_REPO_URL=https://github.com/rz-rinvest/portfolio_trader.git
ENV GIT_BRANCH=main
ENV REPO_FOLDER=./repo

# --- Streamlit dev server ---
# streamlit_app.py is the entry file in the streamlit-example repo
ENV STREAMLIT_DEV_FILE=litdev.py
ENV STREAMLIT_PORT=8501
ENV STREAMLIT_HOST=0.0.0.0

# --- VSCode tunnel (unused in Docker mode, kept for completeness) ---
ENV VSCODE_TUNNEL_NAME=streamlit-dev-machine

# --- Microsoft auth (unused in Docker mode) ---
ENV MS_CLIENT_ID=aebc6443-996d-45c2-90f0-388ff96faa56
ENV MS_TENANT_ID=common
ENV MS_ACCESS_TOKEN=
ENV MS_REFRESH_TOKEN=
ENV MS_TOKEN_EXPIRY=

# --- Runtime flags ---
ENV AUTO_START=false
ENV LOG_LEVEL=INFO

# --- Runtime file paths ---
ENV PID_FILE=.streamlit.pid
ENV TUNNEL_PID_FILE=.tunnel.pid
ENV SOCKET_FILE=.streamlit.sock
ENV LOG_FILE=logs/streamlit.log

# Expose the Streamlit port.
EXPOSE 8501

# ---------------------------------------------------------------------------
# Healthcheck — verify Streamlit is responding on its port.
# Docker will mark the container unhealthy if this fails.
# ---------------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${STREAMLIT_PORT}/_stcore/health || exit 1

# ---------------------------------------------------------------------------
# Entrypoint — run the Docker-specific startup script.
# ---------------------------------------------------------------------------
CMD ["python", "docker/start.py"]
