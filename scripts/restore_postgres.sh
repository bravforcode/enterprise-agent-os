#!/usr/bin/env bash
# Graxia Tool — Postgres restore script
# Usage: ./restore_postgres.sh <backup_file>
#
# Restores a Postgres backup. WARNING: This will overwrite the target database.

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <backup_file.sql.gz>"
    exit 1
fi

BACKUP_FILE="$1"

PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-graxia}"
PG_PASSWORD="${PG_PASSWORD:-graxia_dev}"
PG_DATABASE="${PG_DATABASE:-graxia}"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "WARNING: This will OVERWRITE the database $PG_DATABASE"
echo "Backup file: $BACKUP_FILE"
echo "Target: $PG_HOST:$PG_PORT/$PG_DATABASE"
read -p "Continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Drop and recreate database
echo "Dropping database $PG_DATABASE..."
PGPASSWORD="$PG_PASSWORD" psql \
    --host="$PG_HOST" \
    --port="$PG_PORT" \
    --username="$PG_USER" \
    --dbname=postgres \
    -c "DROP DATABASE IF EXISTS $PG_DATABASE"

echo "Creating database $PG_DATABASE..."
PGPASSWORD="$PG_PASSWORD" psql \
    --host="$PG_HOST" \
    --port="$PG_PORT" \
    --username="$PG_USER" \
    --dbname=postgres \
    -c "CREATE DATABASE $PG_DATABASE"

# Restore
echo "Restoring from backup..."
gunzip -c "$BACKUP_FILE" | PGPASSWORD="$PG_PASSWORD" psql \
    --host="$PG_HOST" \
    --port="$PG_PORT" \
    --username="$PG_USER" \
    --dbname="$PG_DATABASE"

echo "Restore complete."
