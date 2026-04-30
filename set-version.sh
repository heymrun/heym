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

# Sync root package version in uv.lock only (uv has no "metadata-only" lock mode;
# `uv lock` can reorder or refresh deps and create large diffs)
LOCK_FILE="$PROJECT_ROOT/backend/uv.lock"
if [ -f "$LOCK_FILE" ] && command -v python3 &> /dev/null; then
    SET_VERSION_UV_LOCK="$VERSION" SET_VERSION_LOCK_PATH="$LOCK_FILE" python3 << 'PY'
import os
import re
import pathlib

version = os.environ["SET_VERSION_UV_LOCK"]
if any(c in version for c in '"\n\r'):
    raise SystemExit("refusing unsafe version string for uv.lock patch")
path = pathlib.Path(os.environ["SET_VERSION_LOCK_PATH"])
text = path.read_text()
pattern = r'(\[\[package\]\]\r?\nname = "heym-backend"\r?\nversion = )"[^"]*"'
new_text, n = re.subn(pattern, rf'\1"{version}"', text, count=1)
if n != 1:
    raise SystemExit(
        f"uv.lock: expected exactly one heym-backend [[package]] block, matched {n}"
    )
path.write_text(new_text)
PY
elif [ -f "$LOCK_FILE" ]; then
    echo "Warning: python3 not found; skipping uv.lock root version sync" >&2
fi

# Update package.json
if [ -f "$PROJECT_ROOT/frontend/package.json" ]; then
    sed -i.bak 's/"version": ".*"/"version": "'"$VERSION"'"/' "$PROJECT_ROOT/frontend/package.json" && rm "$PROJECT_ROOT/frontend/package.json.bak"
fi

echo "Version updated to $VERSION"
echo "Restart services to apply changes"