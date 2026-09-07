#!/usr/bin/env bash
# The nightly run on weddle (see ops/systemd/): fetch both registers and the
# roster, regenerate data/, commit what changed, push so GitHub Pages rebuilds.
# No model is involved anywhere in this pipeline.
set -euo pipefail

PROJECT_DIR="/home/ben/projects/peculiar-interests"
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/run-$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"
find "$LOG_DIR" -name 'run-*.log' -mtime +60 -delete

eval "$(/home/ben/.local/bin/mise activate bash)"
cd "$PROJECT_DIR"

# Each step may fail without stopping the run (a failed House fetch still
# leaves a Senate parse worth committing), but every failure is recorded and
# re-raised at the end so systemd shows the run as failed, not green.
FAILURES=()
failed() {
  FAILURES+=("$1")
  echo "FAILED: $1" >> "$LOG_FILE"
}
step() {
  echo "=== $1 at $(date -Iseconds) ===" >> "$LOG_FILE"
}

step "fetch"
uv run peculiar fetch roster >> "$LOG_FILE" 2>&1 || failed "fetch roster"
uv run peculiar fetch senate >> "$LOG_FILE" 2>&1 || failed "fetch senate"
uv run peculiar fetch house >> "$LOG_FILE" 2>&1 || failed "fetch house"

step "parse"
uv run peculiar parse >> "$LOG_FILE" 2>&1 || failed parse
uv run peculiar people >> "$LOG_FILE" 2>&1 || failed people
uv run peculiar schema >> "$LOG_FILE" 2>&1 || failed schema

# Raw fetches and the data derived from them land in one commit, so the
# history reads as "what the register said on this date". Nothing to commit is
# the normal case.
step "commit"
git add -- raw data >> "$LOG_FILE" 2>&1 || failed "git add"
if ! git diff --cached --quiet; then
  changed=$(git diff --cached --name-only -- data | grep -c '/48/' || true)
  git commit -m "register: nightly update, ${changed} statements changed" >> "$LOG_FILE" 2>&1 \
    || failed commit
  step "push"
  git push >> "$LOG_FILE" 2>&1 || failed push
else
  echo "no changes" >> "$LOG_FILE"
fi

step "status"
uv run peculiar status >> "$LOG_FILE" 2>&1 || failed status

step "run finished"
if [ ${#FAILURES[@]} -gt 0 ]; then
  echo "run finished with failures: ${FAILURES[*]}" >> "$LOG_FILE"
  exit 1
fi
