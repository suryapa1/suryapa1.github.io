# Eluru ward voter search

A static, searchable website for the Eluru Municipal Corporation ward photo voter lists for 2026, published by AP SEC.

- **Pick a ward** from the dropdown or the tiles. Every ward has its own link: `…/wards/?ward=62`
- **Only the selected ward is downloaded**: one JSON file per ward (`data/wards/<ward>.json`).
- **All wards** mode searches every ward at once. A small badge on each result shows which ward it's from.
- **Search** covers name, relative, house number, voter ID and serial number, in Telugu or English. Matching is forgiving about spelling (aa/a, sh/s, rao/ravu…).
- Results show as **boxes** that mirror the printed roll, or as a **table**. There are filters for part, gender and age. Click a house number to list everyone living there. Any result set can be downloaded as CSV.
- The **Ward summary** tab shows each ward's cover sheet (localities, house-number ranges, totals by part and gender).

## Refresh the data (all wards, one command)
```bash
brew install poppler          # once (Linux: apt-get install poppler-utils)
scripts/refresh.sh /path/to/folder/with/ward-pdfs
git add data/wards && git commit -m "Refresh ward data" && git push
```
`process_ward.py` reads the ward number, assembly, parts and locality table from each PDF's cover sheet. It then checks the extracted voters against the cover sheet: the overall total, the totals by gender and by part, and that serial numbers are complete. It prints `OK ✓` or the exact mismatch, and `index.json` records whether each ward passed. Adding a new ward PDF and re-running the script is all it takes to add that ward.

## Files
```
index.html               the whole UI (no build step)
data/wards/index.json    ward list + totals (loaded first, tiny)
data/wards/<n>.json      one ward: cover-sheet meta + voter rows
scripts/process_ward.py  PDF -> <n>.json with validation
scripts/translit.py      Telugu -> English transliteration used for search
scripts/refresh.sh       batch re-extract
```

## Notes
- English names are machine transliterations, used for searching only.
- `noindex` asks search engines not to list the page. That only keeps it out of search results; anyone with the link can still open it.
