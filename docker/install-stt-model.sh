#!/bin/sh
# Downloads the Whisper model behind the Converter node's audioToText conversion.
# The backend loads whichever ggml-*.bin it finds, so a model swap is the three values below.
# Usage: install-stt-model.sh TARGET_DIR
set -eu

MODEL_FILE="ggml-small-q5_1.bin"
MODEL_SHA256="ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/${MODEL_FILE}"

TARGET_DIR="${1:?usage: install-stt-model.sh TARGET_DIR}"
TARGET="${TARGET_DIR}/${MODEL_FILE}"

checksum() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1
    fi
}

if [ -f "$TARGET" ] && [ "$(checksum "$TARGET")" = "$MODEL_SHA256" ]; then
    exit 0
fi

mkdir -p "$TARGET_DIR"
# A model swap leaves the old file behind; the backend would keep loading it.
rm -f "$TARGET_DIR"/ggml-*.bin
curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 -o "${TARGET}.part" "$MODEL_URL"

if [ "$(checksum "${TARGET}.part")" != "$MODEL_SHA256" ]; then
    rm -f "${TARGET}.part"
    echo "install-stt-model: checksum mismatch for ${MODEL_FILE}" >&2
    exit 1
fi
mv "${TARGET}.part" "$TARGET"
