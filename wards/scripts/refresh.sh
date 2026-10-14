#!/usr/bin/env bash
# Re-extract every ward PDF in a folder and rebuild data/wards/*.json + index.json.
# Usage: scripts/refresh.sh ~/Downloads/eluru-ward-pdfs
set -euo pipefail
DIR="${1:?folder of ward PDFs}"
HERE="$(cd "$(dirname "$0")" && pwd)"
command -v pdftotext >/dev/null || { echo "Install poppler first: brew install poppler"; exit 1; }
python3 -c "import pdfplumber" 2>/dev/null || pip3 install --quiet pdfplumber
python3 "$HERE/process_ward.py" "$DIR"/*.pdf --out "$HERE/../data/wards"
echo "Done. Commit and push data/wards to publish."
