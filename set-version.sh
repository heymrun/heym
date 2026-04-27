#!/bin/bash

# Set Heym Version
# Updates all version-related files with the specified version

VERSION="${1}"

if [ -z "$VERSION" ]; then
    echo "Usage: ./set-version.sh <version>"
    echo "Example: ./set-version.sh 0.2.0"
    exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Setting version to $VERSION..."

# Update VERSION file
echo "$VERSION" > "$PROJECT_ROOT/VERSION"

# Update .env
if [ -f "$PROJECT_ROOT/.env" ]; then
    sed -i.bak "s/APP_VERSION=.*/APP_VERSION=$VERSION/" "$PROJECT_ROOT/.env" && rm "$PROJECT_ROOT/.env.bak"
fi

# Update frontend .env files
if [ -f "$PROJECT_ROOT/frontend/.env.development" ]; then
    sed -i.bak "s/VITE_APP_VERSION=.*/VITE_APP_VERSION=$VERSION/" "$PROJECT_ROOT/frontend/.env.development" && rm "$PROJECT_ROOT/frontend/.env.development.bak"
fi

# Update pyproject.toml
if [ -f "$PROJECT_ROOT/backend/pyproject.toml" ]; then
    sed -i.bak 's/^version = ".*"/version = "'"$VERSION"'"/' "$PROJECT_ROOT/backend/pyproject.toml" && rm "$PROJECT_ROOT/backend/pyproject.toml.bak"
fi

# Update uv.lock
echo "Updating uv.lock..."
cd "$PROJECT_ROOT/backend"
if command -v uv &> /dev/null; then
    uv lock --upgrade-package heym-backend
    echo "uv.lock updated"
else
    echo "Warning: uv command not found, skipping uv.lock update"
fi
cd "$PROJECT_ROOT"

# Update package.json
if [ -f "$PROJECT_ROOT/frontend/package.json" ]; then
    sed -i.bak 's/"version": ".*"/"version": "'"$VERSION"'"/' "$PROJECT_ROOT/frontend/package.json" && rm "$PROJECT_ROOT/frontend/package.json.bak"
fi

echo "Version updated to $VERSION"
echo "Restart services to apply changes"