# Step 1: Collect parameters & confirm

**Confirm each item one by one — do not skip.** Three phases:

## 1a. Collect & display

Extract parameters from the user's command; fill defaults for any not provided, then **print a parameter summary table**:

```text
═══════════════════════════════════════
  md2word parameter confirmation
═══════════════════════════════════════
  MD file:        /path/to/paper.md
  BIB file:       /path/to/references.bib
  CSL style:      physics-in-medicine-and-biology
                  → citation-format: author-date
  Zotero User ID: 0 (local)
  Collection:     references
  Output file:    /path/to/paper_zotero.docx
  ─────────────────────────────────────
  OUTDIR:         /path/to/
═══════════════════════════════════════
```

When a required field is missing you **must pause and ask** — do not substitute a default:

| Parameter | Required | Default | If missing |
|-----------|----------|---------|------------|
| md_file | ✅ | — | **pause, ask for the file path** |
| bib_file | ✅ | — | **pause, ask for the file path** |
| collection | — | BIB filename without extension | use default silently |
| output | — | `OUTDIR/<md_filename>_zotero.docx` | use default silently |
| user_id | — | `0` (local Zotero) | use default silently |
| csl_style | ✅ | `physics-in-medicine-and-biology` | use default if the user does not specify |

> **CSL file path**: the default CSL lives at this skill's `styles/physics-in-medicine-and-biology.csl`. It is a dependent style; the parent is `institute-of-physics-harvard.csl` in the same directory, which pandoc resolves automatically. The path is relative to the skill directory.

## 1b. Environment pre-check

**File checks** — confirm they exist and are in the correct format:

```bash
# check files exist
ls -la MD_FILE BIB_FILE
# count MD citations
grep -c '\[@' MD_FILE
# count BIB entries
grep -c '^@' BIB_FILE
# inspect CSL and show its citation-format
python3 -c "import xml.etree.ElementTree as ET; ..."
```

**Zotero connectivity check** — must pass before Step 2:

```bash
# 1) Is Zotero desktop running? (Local API, read-only)
curl -s http://localhost:23119/api/users/0/collections | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Local API: ✅ {len(d)} collections')" \
  || echo 'Local API: ❌ Zotero not running'

# 2) Is the Zotero Web API available? (read & write, required by Step 3)
curl -s -H "Zotero-API-Key: $ZOTERO_API_KEY" "https://api.zotero.org/users/$ZOTERO_USER_ID/collections?limit=1" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Web API: ✅ user={d[0][\"library\"][\"name\"]}')" \
  || echo 'Web API: ❌ ZOTERO_API_KEY / ZOTERO_USER_ID not configured'
```

Print a summary:
```text
  MD: 118 lines, 50 unique citations
  BIB: 58 entries (26% DOI coverage)
  CSL: author-date (IOP Harvard)
  Zotero Local API: ✅ (read)
  Zotero Web API: ✅ (read & write, required by Step 3-4)
```

- If `ZOTERO_API_KEY` or `ZOTERO_USER_ID` is missing → **ask the user to do it manually**:
  1. Confirm the Collection name with the user (default: BIB filename without extension)
  2. Have the user create that Collection in Zotero
  3. Have the user import the BIB into that Collection via Zotero's "Import" feature
  4. Wait for the user to confirm "import done" before continuing to Step 2

## 1c. Summary confirmation

Show all of the above. **If no required field (md_file, bib_file) is missing, proceed to Step 2 automatically** — no need to wait for a user reply. Pause only when a required field is missing.
