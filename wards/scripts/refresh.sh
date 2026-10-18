#!/usr/bin/env bash
# Re-extract every ward PDF in a folder, rebuild data/wards/*.json + index.json,
# cross-ward house links, and the split-families analysis (splits.json).
# Usage: scripts/refresh.sh ~/Downloads/ward-divisions
set -euo pipefail
DIR="${1:?folder of ward PDFs}"
HERE="$(cd "$(dirname "$0")" && pwd)"
command -v pdftotext >/dev/null || { echo "Install poppler first: brew install poppler"; exit 1; }
python3 -c "import pdfplumber" 2>/dev/null || pip3 install --quiet pdfplumber
python3 "$HERE/process_ward.py" "$DIR"/*.pdf --out "$HERE/../data/wards"
python3 "$HERE/analyze_splits.py" "$HERE/../data/wards"
echo "Done. Commit and push wards/ to publish."
