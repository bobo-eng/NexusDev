#!/bin/bash
# CI/CD script for NexusDev

set -e

echo "🔍 NexusDev CI Pipeline"
echo "======================="

# Install dependencies
echo "Installing dependencies..."
pip install -e ".[dev]"

# Run linter
echo ""
echo "Running linter..."
ruff check .

# Run type checker
echo ""
echo "Running type checker..."
mypy packages/ --ignore-missing-imports

# Run tests
echo ""
echo "Running tests..."
pytest --cov=packages --cov=apps --cov-report=term-missing

# Build Docker image (optional)
if command -v docker &> /dev/null; then
    echo ""
    echo "Building Docker image..."
    docker build -t nexusdev:latest .
fi

echo ""
echo "✅ CI pipeline completed successfully!"
