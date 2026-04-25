#!/usr/bin/env bash
# Daily retention sweep. Prunes files older than 30 days from the
# visitors archive and the moderation directory, plus empty YYYY-MM
# partition dirs in the archive.
#
# Defaults match VPS layout. Override via env for testing.
#
# Usage:
#   retention-sweep.sh             # live: deletes
#   retention-sweep.sh --dry-run   # counts only

set -euo pipefail

RETENTION_DAYS="${RETENTION_DAYS:-30}"
VISITORS_ARCHIVE="${VISITORS_ARCHIVE:-/claude-home/visitors/archive}"
MODERATION_DIR="${MODERATION_DIR:-/claude-home/moderation}"
LOG_FILE="${LOG_FILE:-/claude-home/logs/retention-sweep.log}"

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

ts() { date -Iseconds; }

prune_files() {
    local label="$1"
    local dir="$2"
    local pattern="$3"
    [[ -d "$dir" ]] || return 0
    local count
    count=$(find "$dir" -type f -name "$pattern" -mtime "+$RETENTION_DAYS" | wc -l | tr -d ' ')
    if (( DRY_RUN )); then
        echo "[$(ts)] $label: would prune $count files (dry-run)"
    else
        find "$dir" -type f -name "$pattern" -mtime "+$RETENTION_DAYS" -delete
        echo "[$(ts)] $label: pruned $count files"
    fi
}

prune_empty_dirs() {
    local label="$1"
    local dir="$2"
    [[ -d "$dir" ]] || return 0
    local count
    count=$(find "$dir" -mindepth 1 -type d -empty | wc -l | tr -d ' ')
    if (( DRY_RUN )); then
        echo "[$(ts)] $label: would prune $count empty directories (dry-run)"
    else
        find "$dir" -mindepth 1 -type d -empty -delete
        echo "[$(ts)] $label: pruned $count empty directories"
    fi
}

mkdir -p "$(dirname "$LOG_FILE")"

{
    echo "[$(ts)] retention-sweep start (dry-run=$DRY_RUN, retention=${RETENTION_DAYS}d)"
    prune_files "visitors-archive" "$VISITORS_ARCHIVE" "*.md"
    prune_empty_dirs "visitors-archive" "$VISITORS_ARCHIVE"
    prune_files "moderation" "$MODERATION_DIR" "*.json"
    echo "[$(ts)] retention-sweep complete"
} >> "$LOG_FILE" 2>&1
