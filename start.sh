#!/bin/bash
# LeadCapture AI — Start Script
# Usage: ./start.sh [dev|prod]

set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    exit 1
fi

# Create .env from example if not present
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo "📝 Creating .env from .env.example..."
        cp .env.example .env
        echo "⚠️  Edit .env with your API keys before running in production."
    else
        echo "❌ No .env or .env.example found."
        exit 1
    fi
fi

# Load environment variables (handles spaces in values)
set -a
. .env
set +a

# Install dependencies if needed
if [ ! -d "venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Create data directories
mkdir -p data/logs

MODE="${1:-dev}"

if [ "$MODE" = "prod" ]; then
    echo "🚀 Starting in PRODUCTION mode..."
    echo ""
    echo "  App:     http://localhost:${PORT:-8000}"
    echo "  Admin:   http://localhost:${PORT:-8000}/admin"
    echo "  Health:  http://localhost:${PORT:-8000}/health"
    echo ""

    # Run with uvicorn directly
    exec uvicorn src.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
else
    echo "🔧 Starting in DEVELOPMENT mode..."
    echo ""
    echo "  App:     http://localhost:${PORT:-8000}"
    echo "  Admin:   http://localhost:${PORT:-8000}/admin"
    echo "  Health:  http://localhost:${PORT:-8000}/health"
    echo ""

    # Run with auto-reload
    exec uvicorn src.app:app --host 0.0.0.0 --port ${PORT:-8000} --reload
fi
