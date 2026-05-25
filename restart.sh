#!/usr/bin/env bash
# Quick restart for local dev — kill old web, optionally rebuild, relaunch.
#
# Usage:
#   bash restart.sh              # just restart web
#   bash restart.sh --bg         # restart in background, log to /tmp
#   bash restart.sh --reinstall  # pip install -e . before restart (after deps change)
#   bash restart.sh --daemon     # also restart the scheduler daemon
#   bash restart.sh --port 9000  # use a different port
#
# Tail logs (in --bg mode):
#   tail -f /tmp/rl-agent-web.log
#   tail -f /tmp/rl-agent-daemon.log

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=8765
BG=0
REINSTALL=0
WITH_DAEMON=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bg) BG=1; shift ;;
        --reinstall) REINSTALL=1; shift ;;
        --daemon) WITH_DAEMON=1; shift ;;
        --port) PORT="$2"; shift 2 ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1"; exit 1 ;;
    esac
done

cd "$PROJECT_DIR"

# 1. kill existing
echo "▶ Killing anything on port $PORT..."
lsof -ti:"$PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true

if [ "$WITH_DAEMON" = "1" ]; then
    echo "▶ Killing existing rl-agent daemon..."
    pkill -f "rl-agent daemon" 2>/dev/null || true
fi

# brief grace so port is fully released
sleep 0.5

# 2. activate venv
if [ ! -d ".venv" ]; then
    echo "✗ .venv not found. Run: python3 -m venv .venv && source .venv/bin/activate && pip install -e ."
    exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 3. optional reinstall
if [ "$REINSTALL" = "1" ]; then
    echo "▶ Reinstalling project..."
    pip install -e . >/dev/null
fi

# 4. start daemon (optional)
if [ "$WITH_DAEMON" = "1" ]; then
    echo "▶ Starting daemon in background..."
    nohup rl-agent daemon --idle-days 3 > /tmp/rl-agent-daemon.log 2>&1 &
    echo "    daemon PID $!  → tail -f /tmp/rl-agent-daemon.log"
fi

# 5. start web
if [ "$BG" = "1" ]; then
    echo "▶ Starting web in background on :$PORT..."
    nohup rl-agent serve --host 127.0.0.1 --port "$PORT" > /tmp/rl-agent-web.log 2>&1 &
    echo "    web PID $!  → tail -f /tmp/rl-agent-web.log"
    sleep 1
    if curl -s "http://127.0.0.1:$PORT/api/health" > /dev/null; then
        echo "✓ http://127.0.0.1:$PORT  ready"
    else
        echo "⚠ health check failed; tail /tmp/rl-agent-web.log"
    fi
else
    echo "▶ Starting web on :$PORT (foreground, Ctrl+C to stop)..."
    echo
    exec rl-agent serve --host 127.0.0.1 --port "$PORT"
fi
