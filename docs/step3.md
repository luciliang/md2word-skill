# Step 3: Create Zotero Collection + import authoritative metadata

Use `scripts/import_zotero.py` to import the **authoritative metadata** (not the BIB values) adjudicated by Step 2c into Zotero.

## Prerequisites

- Step 2c produced `verify_result.json` (with `authoritative` metadata per entry)
- `ZOTERO_API_KEY` + `ZOTERO_USER_ID` configured — **the Local API does not support writes** (confirmed in practice); imports/writes must use the Web API

## 3a. Import

```bash
python3 scripts/import_zotero.py \
  --verify-json OUTDIR/verify_result.json \
  --collection COLLECTION_NAME \
  --bib BIB_FILE
```

Optional: `--dry-run` (report only, no writes), `--import-skip` (also import SKIP entries using BIB values, tagged "unverified").

**Script logic**:
- **PASS** → create a new item with authoritative metadata via `create_items`
- **FLAG** → create with authoritative metadata + write the conflict record into the `Extra` field (under `--strict` these already blocked in Step 2c)
- **REJECT / SKIP** → not imported (authenticity doubtful; avoid polluting the library); `--import-skip` forces an import using the BIB value
- An item with the **same DOI** already in the collection → `update_item` to correct (including author names); otherwise `create_items`

## 3b. Core value: fixing BIB errors

Even if an author's name is misspelled in the BIB (e.g. `Fogliato`), three-source arbitration yields the authoritative value (`Fogliata`), so the import is correct from the start. This is the fundamental advantage over "importing the BIB directly" — **BIB errors are overwritten by authoritative data**. The same applies to year, journal, volume-issue-pages.

> ⚠️ Do not use "fill only the DOI and let Zotero auto-complete": pyzotero (Local or Web API) creating an item with only a DOI **does not trigger** the Zotero client's auto-completion (in practice it yields an incomplete entry). You must build the full payload from verify's authoritative data.

## 3c. Wait for sync & verify

`sleep 5`, then confirm the number of entries in the collection. **Re-run** `import_zotero.py` — everything should report `↻ update` (no duplicate creation for the same DOI) — this validates deduplication correctness.

**Checkpoint**: show the import report (created / updated / FLAG / skipped) and wait for the user to confirm.

> REJECT/SKIP are not imported — references whose authenticity is doubtful should not pollute the Zotero library. FLAG has been imported (with the best value), but its `Extra` field carries a conflict record you should review one by one before submission.
