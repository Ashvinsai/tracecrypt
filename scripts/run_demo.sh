#!/usr/bin/env bash
#
# Local, read-only demo launcher for the investigator console.
#
# Starts the existing FastAPI app and prints the console URLs. The saved demo
# path needs no Docker, no Redis, no database migration, no login, and no live
# provider credentials -- the console reads already-saved artifacts on disk.
#
#   ./scripts/run_demo.sh            # http://127.0.0.1:8010/investigator
#   DEMO_PORT=9000 ./scripts/run_demo.sh
#
# Default port 8010, not 8000, so the demo does not collide with an unrelated
# dev server the operator may already have on 8000.
#
# This launcher never installs dependencies. Run `make demo-prepare` once first
# (it installs the frontend dependencies, builds the workspace, and verifies the
# demo artifacts). If the prepared workspace is missing, this script says so and
# exits rather than silently falling back -- /investigator must never disappear
# without telling the operator.
#
# This is a prototype launcher, not a deployment tool.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

HOST="${DEMO_HOST:-127.0.0.1}"
PORT="${DEMO_PORT:-8010}"

fail() {
  echo "error: $*" >&2
  exit 1
}

if ! command -v uv >/dev/null 2>&1; then
  fail "'uv' is required (https://docs.astral.sh/uv/). Install it, then run: make demo-prepare"
fi

if [ ! -d api/.venv ]; then
  fail "api/.venv is missing. Run 'make demo-prepare' once (it installs the Python and frontend dependencies and builds the investigator workspace)."
fi

# The investigator workspace is served from frontend/dist, which is not tracked
# in git. Build it from an existing node_modules without touching the network;
# otherwise stop loudly so /investigator never silently goes missing.
if [ ! -f frontend/dist/index.html ]; then
  if [ -d frontend/node_modules ]; then
    command -v npm >/dev/null 2>&1 || fail "frontend/dist is missing and 'npm' is not on PATH. Run 'make demo-prepare'."
    echo "note: building the investigator workspace (frontend/dist)..." >&2
    (cd frontend && npm run build) || fail "frontend build failed. Run 'make demo-prepare' to diagnose."
  else
    fail "frontend/dist and frontend/node_modules are both missing, so /investigator cannot be served.
       Run 'make demo-prepare' once (installs frontend dependencies and builds the workspace),
       then run this launcher again."
  fi
fi

# The synthetic trace/report are built offline. This uses the installed Python
# environment only; it never installs anything.
if [ ! -f var/trace.json ] || [ ! -f var/trace-report.html ]; then
  echo "note: synthetic demo artifacts are missing; building them offline..." >&2
  (cd api && CFA_DATA_MODE=SYNTHETIC uv run python ../scripts/trace_demo.py)
fi
if [ ! -f var/live-validation/20260920T090201Z-969305/trace.json ]; then
  echo "note: the optional recorded OKX preset has no saved trace on disk." >&2
  echo "      The synthetic preset is the default. See docs/DEMO_RUNBOOK.md." >&2
fi

echo
echo "Crypto Attribution Triage - local read-only prototype"
echo "  Investigator workspace: http://${HOST}:${PORT}/investigator"
echo "  Overview:  http://${HOST}:${PORT}/"
echo "  Demo:      http://${HOST}:${PORT}/console"
echo "  Dashboard: http://${HOST}:${PORT}/dashboard"
echo "  API docs:  http://${HOST}:${PORT}/docs"
echo "  Stop:      Ctrl-C"
echo

cd api
exec uv run uvicorn app.main:app --host "$HOST" --port "$PORT"
