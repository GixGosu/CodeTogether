#!/bin/bash
# Start development services

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load environment
if [ -f "$PROJECT_DIR/.env" ]; then
    export $(cat "$PROJECT_DIR/.env" | grep -v '^#' | xargs)
fi

usage() {
    echo "Usage: $0 [wrapper|bot|all]"
    echo ""
    echo "Commands:"
    echo "  wrapper  - Start the Python wrapper service"
    echo "  bot      - Start the Rust Discord bot"
    echo "  all      - Start both services (wrapper in background)"
    exit 1
}

start_wrapper() {
    echo "Starting wrapper service..."
    cd "$PROJECT_DIR/wrapper"

    if [ ! -d ".venv" ]; then
        echo "Error: Virtual environment not found. Run ./scripts/dev-setup.sh first."
        exit 1
    fi

    source .venv/bin/activate
    uvicorn wrapper.main:app --reload --host 0.0.0.0 --port ${WRAPPER_PORT:-8000}
}

start_bot() {
    echo "Starting Discord bot..."
    cd "$PROJECT_DIR/bot"
    cargo run
}

start_all() {
    echo "Starting all services..."

    # Start wrapper in background
    cd "$PROJECT_DIR/wrapper"
    source .venv/bin/activate
    uvicorn wrapper.main:app --host 0.0.0.0 --port ${WRAPPER_PORT:-8000} &
    WRAPPER_PID=$!

    # Give wrapper time to start
    sleep 2

    # Start bot in foreground
    cd "$PROJECT_DIR/bot"
    cargo run

    # Clean up wrapper when bot exits
    kill $WRAPPER_PID 2>/dev/null || true
}

case "${1:-}" in
    wrapper)
        start_wrapper
        ;;
    bot)
        start_bot
        ;;
    all)
        start_all
        ;;
    *)
        usage
        ;;
esac
