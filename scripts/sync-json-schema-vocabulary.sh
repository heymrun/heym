#!/bin/sh
# Sync shared/json-schema-vocabulary.json into package-local runtime/build paths.
# Source of truth: shared/json-schema-vocabulary.json

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$REPO_ROOT/shared/json-schema-vocabulary.json"
BACKEND_TARGET="$REPO_ROOT/backend/app/services/json_schema_vocabulary.json"
FRONTEND_TARGET="$REPO_ROOT/frontend/src/lib/jsonSchemaVocabulary.json"

if [ ! -f "$SOURCE" ]; then
  echo "Missing vocabulary source: $SOURCE" >&2
  exit 1
fi

check_matches() {
  target="$1"
  if [ ! -f "$target" ]; then
    echo "Missing synced vocabulary: $target" >&2
    return 1
  fi
  if ! cmp -s "$SOURCE" "$target"; then
    echo "Out-of-date vocabulary copy: $target" >&2
    echo "Run: sh scripts/sync-json-schema-vocabulary.sh" >&2
    return 1
  fi
  return 0
}

if [ "${1:-}" = "--check" ]; then
  check_matches "$BACKEND_TARGET"
  check_matches "$FRONTEND_TARGET"
  echo "JSON Schema vocabulary copies are up to date"
  exit 0
fi

mkdir -p "$(dirname "$BACKEND_TARGET")" "$(dirname "$FRONTEND_TARGET")"
cp "$SOURCE" "$BACKEND_TARGET"
cp "$SOURCE" "$FRONTEND_TARGET"
echo "Synced JSON Schema vocabulary -> backend and frontend package paths"
