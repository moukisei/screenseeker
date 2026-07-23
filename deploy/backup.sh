#!/usr/bin/env bash
# Back up the ScreenSeeker database.
#
# Uses `sqlite3 .backup`, not `cp`: in WAL mode recent writes live in the -wal
# sidecar until a checkpoint, so copying the main file alone can capture a
# torn, partial database. `.backup` takes a consistent snapshot while the app
# keeps running.
#
# Wire it to cron via deploy/screenseeker.cron.

set -euo pipefail

DB_PATH="${SCREENSEEKER_DB_PATH:-/var/lib/screenseeker/screenseeker.db}"
BACKUP_DIR="${SCREENSEEKER_BACKUP_DIR:-/var/lib/screenseeker/backups}"
KEEP="${SCREENSEEKER_BACKUP_KEEP:-14}"

if [[ ! -f "$DB_PATH" ]]; then
	echo "backup: no database at $DB_PATH" >&2
	exit 1
fi

mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
dest="$BACKUP_DIR/screenseeker-$stamp.db"

sqlite3 "$DB_PATH" ".backup '$dest'"
gzip "$dest"
echo "backup: wrote $dest.gz"

# Keep the newest $KEEP, delete the rest.
ls -1t "$BACKUP_DIR"/screenseeker-*.db.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
	rm -f "$old"
	echo "backup: pruned $old"
done
