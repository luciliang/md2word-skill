# Step 4: cite_key → Zotero item key mapping (produced by Step 3 import)

**The mapping is now produced directly by Step 3's `import_zotero.py`** — no need to read the collection separately (saves a network round-trip and avoids jitter when reading the collection).

During import, every create/update records cite_key → zotero_key, tagged with **confidence and anchor**.

Outputs `mapping.json` (in the verify.json directory by default; override with `--output-mapping`), one entry per record:
```json
{"cite_key": {"zotero_key": "ABCD1234", "anchor": "doi", "confidence": "high", "status": "PASS"}}
```

**Confidence tiers** (for audit; reflect mapping reliability):
- `high` / `doi` — precise DOI anchor (most reliable; three-source verified)
- `medium` / `title` — no DOI, matched via title reverse lookup
- `low` / `bib` — SKIP entry imported using the BIB value (not three-source verified; requires `--import-skip`)

At the end of the import, all non-high (low-confidence) mappings are listed and **manual review is recommended**. `inject_zotero.py` is compatible with this new format (also backward-compatible with the old simple `{ck: key}` format).

**Checkpoint**: review the low-confidence list from the import output and decide whether medium/low mappings are acceptable; for those that are not, manually fix `mapping.json` and re-run inject.
