#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${MODEL_DIR:-/models}"
LLM_URL="https://huggingface.co/Qwen/Qwen2-VL-2B-Instruct-GGUF/resolve/main/qwen2-vl-2b-instruct-q4_k_m.gguf"
LLM_SHA256="PLACEHOLDER_UPDATE_AFTER_FIRST_DOWNLOAD"
LLM_FILE="$MODEL_DIR/Qwen2-VL-2B-Instruct-Q4_K_M.gguf"

MMPROJ_URL="https://huggingface.co/bartowski/Qwen2-VL-2B-Instruct-GGUF/resolve/main/mmproj-Qwen2-VL-2B-Instruct-f16.gguf"
MMPROJ_SHA256="PLACEHOLDER_UPDATE_AFTER_FIRST_DOWNLOAD"
MMPROJ_FILE="$MODEL_DIR/mmproj-Qwen2-VL-2B-Instruct-f16.gguf"

download_and_verify() {
    local url="$1" file="$2" expected_sha="$3"
    if [[ -f "$file" ]]; then
        actual=$(sha256sum "$file" | awk '{print $1}')
        if [[ "$actual" == "$expected_sha" ]]; then
            echo "✓ $(basename "$file") already present and verified"
            return 0
        fi
        echo "⚠ $(basename "$file") checksum mismatch, re-downloading..."
        rm -f "$file"
    fi
    echo "⬇ Downloading $(basename "$file")..."
    curl -L --retry 3 --retry-delay 5 -o "$file" "$url"
    actual=$(sha256sum "$file" | awk '{print $1}')
    if [[ "$actual" != "$expected_sha" ]]; then
        echo "ERROR: SHA256 mismatch for $(basename "$file")"
        echo "  Expected: $expected_sha"
        echo "  Got:      $actual"
        rm -f "$file"
        exit 1
    fi
    echo "✓ $(basename "$file") verified"
}

mkdir -p "$MODEL_DIR"
download_and_verify "$LLM_URL" "$LLM_FILE" "$LLM_SHA256"
download_and_verify "$MMPROJ_URL" "$MMPROJ_FILE" "$MMPROJ_SHA256"
echo "All models ready."
