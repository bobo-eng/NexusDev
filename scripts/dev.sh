#!/bin/bash
# Development script for NexusDev

set -e

echo "🚀 NexusDev Development Environment"
echo "===================================="

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

# Create virtual environment if not exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -e ".[dev]"

# Create database
echo "Setting up database..."
python3 -c "
import asyncio
from core.storage.database import create_database

async def setup():
    db = create_database()
    await db.create_tables()
    print('Database tables created')

asyncio.run(setup())
"

echo ""
echo "✅ Development environment ready!"
echo ""
echo "Available commands:"
echo "  nexusdev --help          # CLI help"
echo "  nexusdev version         # Show version"
echo "  nexusdev create ...      # Create session"
echo "  uvicorn apps.api.main:app --reload  # Start API"
echo ""
echo "Run tests:"
echo "  pytest                   # Run all tests"
echo "  pytest tests/unit        # Run unit tests"
echo "  ruff check .             # Run linter"
echo "  mypy packages/           # Run type checker"
