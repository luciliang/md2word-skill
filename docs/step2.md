# Step 2: Dependency check + verification

## 2a. Check dependencies

```bash
# Local API for reads; Step 3 writes must use the Web API
python3 -c "from pyzotero import zotero; zot = zotero.Zotero(0, 'user', local=True); print(len(zot.collections()), 'collections')"
pandoc --version | head -1
```

If Zotero is not running, prompt the user to start it and retry.

## 2b + 2c. Cross-validation + three-source verification & metadata arbitration

Call `scripts/verify_references.py`:

```bash
# cross-validation only (fast, default)
python3 scripts/verify_references.py MD_FILE BIB_FILE

# cross-validation + three-source verification (full path)
python3 scripts/verify_references.py MD_FILE BIB_FILE --verify

# FLAG also blocks (pre-submission final review)
python3 scripts/verify_references.py MD_FILE BIB_FILE --verify --strict

# output JSON (with authoritative metadata) for Step 3 import
python3 scripts/verify_references.py MD_FILE BIB_FILE --verify --json OUTDIR/verify_result.json
```

**Three sources** (all free, no key):
- **CrossRef** — DOI anchor / journal / volume-issue-pages / year (publisher-direct)
- **PubMed** (NCBI E-utilities) — biomedical gold standard / most rigorous author full-names (NLM independent curation)
- **OpenAlex** — broadest coverage / author affiliations / ORCID

**Arbitration flow**: normalize to eliminate false conflicts → judge whether it's the same paper → four-tier disposition
- ✅ **PASS**: three sources agree (or agree after normalization)
- ⚠️ **FLAG**: substantive conflict but a reasonable default → **non-blocking** by default (import but tag in Extra); blocks under `--strict`
- ❌ **REJECT**: doesn't look like the same paper (title/author/year mismatch) → not imported
- ⏭ **SKIP**: not found in any source → not imported

**Field best-source** (who wins on real conflicts): authors prefer **PubMed** (independently curated, a single vote carries weight ≥ CrossRef + OpenAlex); journal/volume-issue-pages/year prefer **CrossRef**.

> ⚠️ Sources are not independent: OpenAlex inherits much of its data from CrossRef, so votes are not simply counted; PubMed's independent vote carries more weight.

**Checkpoint**: the script prints a report (PASS/FLAG/REJECT/SKIP counts + per-field conflict details for FLAG). Under `--strict`, FLAG/REJECT block.

> `verify_result.json` carries the `authoritative` metadata for every entry, consumed by `import_zotero.py` in Step 3 — this is the key to "don't trust the BIB, use authoritative data" for fixing errors.
