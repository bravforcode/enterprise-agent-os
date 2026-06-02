#!/usr/bin/env bash
# Graxia Tool — Qdrant backup script
# Usage: ./backup_qdrant.sh [output_dir]
#
# Creates a snapshot of all Qdrant collections.
# Default output: ./backups/qdrant_YYYY-MM-DD_HHMMSS/

set -euo pipefail

QDRANT_HOST="${QDRANT_HOST:-localhost}"
QDRANT_PORT="${QDRANT_PORT:-6333}"
BACKUP_DIR="${1:-./backups}"

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y-%m-%d_%H%M%S")
SNAPSHOT_DIR="$BACKUP_DIR/qdrant_${TIMESTAMP}"
mkdir -p "$SNAPSHOT_DIR"

echo "Starting Qdrant backup from $QDRANT_HOST:$QDRANT_PORT..."
echo "Output: $SNAPSHOT_DIR"

# List all collections
echo "Listing collections..."
COLLECTIONS=$(curl -s "http://$QDRANT_HOST:$QDRANT_PORT/collections" | python -c "import json,sys; print(' '.join([c['name'] for c in json.load(sys.stdin)['result']['collections']]))")

if [ -z "$COLLECTIONS" ]; then
    echo "No collections found."
    exit 0
fi

echo "Found collections: $COLLECTIONS"

# Snapshot each collection
for col in $COLLECTIONS; do
    echo "Snapshotting $col..."
    SNAPSHOT_NAME=$(curl -s -X POST "http://$QDRANT_HOST:$QDRANT_PORT/collections/$col/snapshots" | python -c "import json,sys; print(json.load(sys.stdin)['result']['name'])")
    echo "  Snapshot: $SNAPSHOT_NAME"

    # Download snapshot
    curl -s -o "$SNAPSHOT_DIR/${col}_${SNAPSHOT_NAME}.snapshot" \
        "http://$QDRANT_HOST:$QDRANT_PORT/collections/$col/snapshots/$SNAPSHOT_NAME"
done

# Compress
echo "Compressing..."
tar -czf "${SNAPSHOT_DIR}.tar.gz" -C "$BACKUP_DIR" "$(basename "$SNAPSHOT_DIR")"
rm -rf "$SNAPSHOT_DIR"

SIZE=$(du -h "${SNAPSHOT_DIR}.tar.gz" | cut -f1)
echo "Qdrant backup complete: ${SNAPSHOT_DIR}.tar.gz ($SIZE)"

# Cleanup old backups (keep 30 days)
find "$BACKUP_DIR" -name "qdrant_*.tar.gz" -mtime +30 -delete 2>/dev/null || true

echo "Done."
