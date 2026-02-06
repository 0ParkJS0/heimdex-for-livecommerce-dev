#!/bin/bash
set -e

echo "🏗️  Starting Heimdex development environment..."

# Check prerequisites
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is required but not installed."
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    echo "❌ Docker Compose is required but not installed."
    exit 1
fi

# Add hosts entry if not present
if ! grep -q "devorg.app.heimdex.local" /etc/hosts; then
    echo "📝 Adding devorg.app.heimdex.local to /etc/hosts (requires sudo)..."
    echo "127.0.0.1 devorg.app.heimdex.local" | sudo tee -a /etc/hosts
fi

# Start services
echo "🚀 Starting Docker services..."
docker compose up -d --build

# Wait for services to be healthy
echo "⏳ Waiting for services to be healthy..."
sleep 10

# Check health
until curl -s http://localhost:8000/health > /dev/null 2>&1; do
    echo "   Waiting for API..."
    sleep 2
done

until curl -s http://localhost:9200/_cluster/health > /dev/null 2>&1; do
    echo "   Waiting for OpenSearch..."
    sleep 2
done

# Run migrations
echo "🔄 Running database migrations..."
docker compose exec -T api alembic upgrade head

# Seed data
echo "🌱 Seeding database and OpenSearch..."
docker compose exec -T api python -m app.seed

echo ""
echo "✅ Heimdex is ready!"
echo ""
echo "   Web UI:    http://localhost:3000"
echo "   API Docs:  http://localhost:8000/docs"
echo "   API URL:   http://devorg.app.heimdex.local:8000"
echo ""
echo "   Try searching for: 회의, 프로젝트, 보안, meeting, security"
echo ""
