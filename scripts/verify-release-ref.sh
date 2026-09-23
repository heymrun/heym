#!/bin/sh
# Run from the checkout being released; never publish an unmerged or mismatched tag.
set -eu

release_tag="${1:?Usage: verify-release-ref.sh <tag>}"
release_version="$(cat VERSION)"

if [ -z "$release_version" ] || [ "$release_tag" != "v$release_version" ]; then
    echo "Error: release tag must match v<VERSION>." >&2
    exit 1
fi

tag_commit="$(git rev-parse --verify "refs/tags/$release_tag^{commit}")"
checkout_commit="$(git rev-parse --verify HEAD)"
if [ "$tag_commit" != "$checkout_commit" ]; then
    echo "Error: release tag does not point to the checked-out commit." >&2
    exit 1
fi

if ! git merge-base --is-ancestor HEAD refs/remotes/origin/main; then
    echo "Error: release commit must be present on origin/main." >&2
    exit 1
fi

echo "Verified $release_tag: matches VERSION and is present on origin/main."
