#!/bin/bash
# Scale worker containers (Phase 2)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

usage() {
    echo "Usage: $0 <count>"
    echo ""
    echo "Scale the number of worker containers."
    echo ""
    echo "Arguments:"
    echo "  count  - Number of worker instances (1-10)"
    echo ""
    echo "Example:"
    echo "  $0 5  # Scale to 5 workers"
    exit 1
}

if [ -z "$1" ]; then
    usage
fi

COUNT=$1

if ! [[ "$COUNT" =~ ^[0-9]+$ ]] || [ "$COUNT" -lt 1 ] || [ "$COUNT" -gt 10 ]; then
    echo "Error: Count must be a number between 1 and 10"
    exit 1
fi

echo "Scaling workers to $COUNT instances..."
cd "$PROJECT_DIR/docker"

docker-compose up -d --scale worker=$COUNT

echo "Workers scaled to $COUNT instances."
docker-compose ps worker
