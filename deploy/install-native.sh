#!/usr/bin/env bash
# RL Agent Tutor — one-command install for native deployment.
#
# Usage:
#   cd rl-agent-tutor
#   bash deploy/install-native.sh
#
# What it does:
#   1. Creates a venv at .venv if missing
#   2. pip install -e . inside it
#   3. Detects macOS / Linux and installs the right service files
#   4. Replaces YOUR_USERNAME / path placeholders with real paths
#   5. Loads/enables the services
#
# Idempotent: re-running upgrades the install.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$PROJECT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "▶ Project: $PROJECT_DIR"

# ---- 1. venv ----
if [ ! -d "$VENV" ]; then
    echo "▶ Creating venv at $VENV"
    "$PYTHON_BIN" -m venv "$VENV"
fi

# ---- 2. install ----
echo "▶ Installing project + dependencies"
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -e "$PROJECT_DIR"

# ---- 3. .env check ----
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "▶ .env not found. Copying from .env.example"
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "  ⚠️  Edit $PROJECT_DIR/.env and fill in your API key BEFORE starting services"
    echo "     (the services will fail until you do)"
fi

# ---- 4. detect OS and install service ----
case "$(uname -s)" in
    Darwin)
        echo "▶ macOS detected — installing launchd plists"
        LA_DIR="$HOME/Library/LaunchAgents"
        LOG_DIR="$HOME/Library/Logs/rl-agent-tutor"
        mkdir -p "$LA_DIR" "$LOG_DIR"

        for svc in web daemon; do
            src="$PROJECT_DIR/deploy/com.rlagent.$svc.plist"
            dst="$LA_DIR/com.rlagent.$svc.plist"
            sed \
                -e "s|/Users/YOUR_USERNAME/path/to/rl-agent-tutor|$PROJECT_DIR|g" \
                -e "s|/Users/YOUR_USERNAME/Library/Logs|$HOME/Library/Logs|g" \
                "$src" > "$dst"

            # reload if already loaded
            launchctl unload "$dst" 2>/dev/null || true
            launchctl load -w "$dst"
            echo "  ✓ $dst loaded"
        done

        echo
        echo "  Web UI:    http://127.0.0.1:8765"
        echo "  Logs:      $LOG_DIR/"
        echo "  Stop web:  launchctl unload -w $LA_DIR/com.rlagent.web.plist"
        echo "  Stop daem: launchctl unload -w $LA_DIR/com.rlagent.daemon.plist"
        ;;

    Linux)
        echo "▶ Linux detected — installing systemd user units"
        SD_DIR="$HOME/.config/systemd/user"
        mkdir -p "$SD_DIR"

        for svc in rl-agent-web rl-agent-daemon; do
            src="$PROJECT_DIR/deploy/$svc.service"
            dst="$SD_DIR/$svc.service"
            sed "s|%h/path/to/rl-agent-tutor|$PROJECT_DIR|g" "$src" > "$dst"
            echo "  ✓ $dst written"
        done

        systemctl --user daemon-reload
        systemctl --user enable --now rl-agent-web.service rl-agent-daemon.service

        # ensure services keep running after logout
        loginctl enable-linger "$(whoami)" 2>/dev/null \
            || echo "  (skipping enable-linger — needs root; services stop on logout otherwise)"

        echo
        echo "  Web UI:    http://127.0.0.1:8765"
        echo "  Status:    systemctl --user status rl-agent-web rl-agent-daemon"
        echo "  Logs:      journalctl --user -u rl-agent-web -f"
        echo "  Stop:      systemctl --user stop rl-agent-web rl-agent-daemon"
        ;;

    *)
        echo "❌ Unsupported OS: $(uname -s). Manual setup required."
        exit 1
        ;;
esac

echo
echo "✔ Done. Open http://127.0.0.1:8765 in your browser."
