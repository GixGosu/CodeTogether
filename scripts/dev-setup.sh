#!/bin/bash
# Development environment setup script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Setting up development environment..."

# Check for required tools
check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo "Error: $1 is not installed. Please install it first."
        exit 1
    fi
}

echo "Checking required tools..."
check_command python3
check_command cargo
check_command npm

# Check for Claude Code CLI
if ! command -v claude &> /dev/null; then
    echo "Warning: Claude Code CLI not found."
    echo "Install it with: npm install -g @anthropic-ai/claude-code"
fi

# Setup Python environment
echo "Setting up Python environment..."
cd "$PROJECT_DIR/wrapper"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install -e ".[dev]"

# Build Rust project (check only)
echo "Checking Rust project..."
cd "$PROJECT_DIR/bot"
cargo check

# Copy environment template if needed
cd "$PROJECT_DIR"
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "Created .env file. Please edit it with your credentials:"
    echo "  - DISCORD_TOKEN: Your Discord bot token"
    echo "  - DISCORD_GUILD_ID: Your test server ID"
    echo "  - ANTHROPIC_API_KEY: Your Anthropic API key"
fi

echo ""
echo "Setup complete!"
echo ""
echo "To start development:"
echo "  1. Edit .env with your credentials"
echo "  2. Start the wrapper: ./scripts/dev-up.sh wrapper"
echo "  3. Start the bot: ./scripts/dev-up.sh bot"
