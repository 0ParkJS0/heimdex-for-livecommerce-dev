#!/usr/bin/env bash
# Download Korean-compatible fonts for the shorts render worker.
# Run once, commit TTF/OTF files to services/shorts-render-worker/fonts/.
#
# Two-tier asset strategy (2026-05-26):
#   * Tier 1 (auto-fetch): Pretendard + Noto Sans KR are OFL 1.1 and
#     published with stable raw-URL releases on GitHub. This script
#     fetches them from upstream so a fresh worker repo bootstrap
#     only needs ``bash scripts/download-fonts.sh``.
#   * Tier 2 (manual commit): the six additional Korean families
#     introduced alongside heimdex-media-contracts 0.20.0
#     (S-Core Dream, NanumSquare, SUIT, KoPubWorldDotum,
#     Onglyph Positive, A2Z) ship as committed binary assets
#     because their upstream distributions either gate downloads
#     behind a noonnu.cc CAPTCHA or don't publish stable raw URLs.
#     Source-of-truth assets live in
#     services/web/public/fonts/<family>/ on the editor side; copy
#     them across when adding a new family. The corresponding
#     contracts font registry pins the exact base
#     filename worker-side; rename one without updating the other
#     and ``resolve_font_path`` will raise ``FontNotFoundError``
#     at boot via ``worker.py::_verify_fonts_or_exit``.
#
# ffmpeg drawtext works with both OTF and TTF regardless of extension.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FONTS_DIR="${SCRIPT_DIR}/../fonts"
mkdir -p "$FONTS_DIR"

# ── Tier 1: auto-fetch ──────────────────────────────────────────────

echo "Downloading Noto Sans KR (OFL 1.1)..."
curl -fsSL -o "$FONTS_DIR/NotoSansKR-Regular.ttf" \
    "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/KR/NotoSansKR-Regular.otf"
curl -fsSL -o "$FONTS_DIR/NotoSansKR-Bold.ttf" \
    "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/KR/NotoSansKR-Bold.otf"

echo "Downloading Pretendard (OFL 1.1)..."
PRETENDARD_VERSION="v1.3.9"
curl -fsSL -o "$FONTS_DIR/Pretendard-Regular.ttf" \
    "https://github.com/orioncactus/pretendard/raw/${PRETENDARD_VERSION}/packages/pretendard/dist/public/static/Pretendard-Regular.otf"
curl -fsSL -o "$FONTS_DIR/Pretendard-Bold.ttf" \
    "https://github.com/orioncactus/pretendard/raw/${PRETENDARD_VERSION}/packages/pretendard/dist/public/static/Pretendard-Bold.otf"

# ── Tier 2: manual-commit sanity check ─────────────────────────────
# These files MUST be present on disk via git. Fail fast with a clear
# message if any are missing — a worker started without them will hit
# FontNotFoundError on the first composition that selects the family.

declare -a TIER2_FILES=(
    "SCDream4-Regular.otf"
    "SCDream6-Bold.otf"
    "NanumSquare-Regular.otf"
    "NanumSquare-Bold.otf"
    "SUIT-Regular.otf"
    "SUIT-Bold.otf"
    "KoPubWorldDotum-Regular.otf"
    "KoPubWorldDotum-Bold.otf"
    "OnglyphPositive-Regular.ttf"
    "A2Z-Regular.ttf"
    "A2Z-SemiBold.ttf"
)

missing=()
for f in "${TIER2_FILES[@]}"; do
    [[ -f "$FONTS_DIR/$f" ]] || missing+=("$f")
done
if (( ${#missing[@]} > 0 )); then
    echo "ERROR: tier-2 (manual-commit) fonts missing from $FONTS_DIR:" >&2
    printf '  - %s\n' "${missing[@]}" >&2
    echo "Copy them from services/web/public/fonts/<family>/ in the editor repo." >&2
    exit 1
fi

echo "Downloaded fonts:"
ls -lh "$FONTS_DIR"/*.ttf "$FONTS_DIR"/*.otf 2>/dev/null
echo "Done."
