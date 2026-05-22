#!/usr/bin/env bash
# Sample backup script for ~/finances/data.db, the shared SQLite store
# the personal-finance plugin family writes to. NOT installed by the
# plugin - copy this file to ~/finances/scripts/backup_db.sh, edit the
# RCLONE_REMOTE variable, and wire it to a cron / launchd job as you
# prefer. The plugin code never touches your backups.
#
# Threat model: the store contains every transaction across all your
# connected banks, plus categorization rules referencing personal
# merchants. Treat the backup target with the same care as a banking
# document.
#
# What the script does
# --------------------
# 1. `sqlite3 .backup` writes a consistent on-disk snapshot even while
#    Claude / monobank-mcp / privat24-skill have the WAL open.
#    Cheaper and safer than `cp data.db` (which would catch WAL in mid
#    flight) and `vacuum into` (which also acquires a write lock).
# 2. The snapshot is gzipped and timestamped under $BACKUP_DIR.
# 3. `rclone copy` mirrors the new file to a remote you control.
#    Override RCLONE_REMOTE in the user environment or just edit this
#    file - the default below is intentionally invalid so the script
#    fails loudly on first run rather than silently dropping the
#    snapshot.
# 4. Snapshots older than RETENTION_DAYS are pruned locally; remote
#    retention is your remote's problem.
#
# Usage
# -----
#   MONOBANK_MCP_DATA_DIR=~/finances RCLONE_REMOTE=mybox:finances-backups \
#       ~/finances/scripts/backup_db.sh

set -euo pipefail

DATA_DIR="${MONOBANK_MCP_DATA_DIR:-$HOME/finances}"
SOURCE_DB="$DATA_DIR/data.db"
BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:-CHANGE_ME:finances-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

if [ ! -f "$SOURCE_DB" ]; then
    echo "backup_db.sh: $SOURCE_DB does not exist; nothing to back up" >&2
    exit 1
fi

if [ "$RCLONE_REMOTE" = "CHANGE_ME:finances-backups" ]; then
    echo "backup_db.sh: set RCLONE_REMOTE to a configured rclone target before running" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
TARGET="$BACKUP_DIR/data-$STAMP.db"

# Online snapshot: sqlite3 grabs the right locks and is safe against a
# concurrent WAL writer. Output is a single .db file (no -wal/-shm).
sqlite3 "$SOURCE_DB" ".backup '$TARGET'"

# Compress in place so the upload is small. .db.gz is fine for archival;
# restore is `gunzip -c data-X.db.gz | sqlite3 data-restored.db ".restore '/dev/stdin'"`
# OR simpler: gunzip the file and open the resulting .db directly.
gzip -- "$TARGET"
TARGET="$TARGET.gz"
echo "snapshot: $TARGET"

# Push to the configured rclone remote. --immutable means rclone refuses
# to overwrite an existing file with the same name (we shouldn't ever
# generate a duplicate stamp, but defence-in-depth).
rclone copy --immutable "$TARGET" "$RCLONE_REMOTE/"

# Prune local snapshots beyond the retention window. Remote retention is
# whatever your remote provider's lifecycle policy dictates.
find "$BACKUP_DIR" -name 'data-*.db.gz' -mtime "+$RETENTION_DAYS" -print -delete
