#!/usr/bin/env bash
# Graxia Tool — Postgres backup script
# Usage: ./backup_postgres.sh [output_dir]
#
# Creates a compressed SQL dump of the graxia database.
# Default output: ./backups/postgres_YYYY-MM-DD_HHMMSS.sql.gz

set -euo pipefail

# Configuration
PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-graxia}"
PG_PASSWORD="${PG_PASSWORD:-graxia_dev}"
PG_DATABASE="${PG_DATABASE:-graxia}"
BACKUP_DIR="${1:-./backups}"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Generate timestamp
TIMESTAMP=$(date +"%Y-%m-%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/postgres_${TIMESTAMP}.sql.gz"

# Run backup
echo "Starting backup of $PG_DATABASE@$PG_HOST:$PG_PORT..."
echo "Output: $BACKUP_FILE"

PGPASSWORD="$PG_PASSWORD" pg_dump \
    --host="$PG_HOST" \
    --port="$PG_PORT" \
    --username="$PG_USER" \
    --dbname="$PG_DATABASE" \
    --no-owner \
    --no-privileges \
    --format=plain \
    --clean \
    --if-exists \
    | gzip > "$BACKUP_FILE"

# Verify backup
if [ ! -s "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file is empty!"
    exit 1
fi

# Get file size
SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup complete: $BACKUP_FILE ($SIZE)"

# Optional: cleanup old backups (keep last 30 days)
find "$BACKUP_DIR" -name "postgres_*.sql.gz" -mtime +30 -delete 2>/dev/null || true

echo "Done."
