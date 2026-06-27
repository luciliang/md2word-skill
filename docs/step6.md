# Step 6: Inject Zotero field codes

Choose the injection strategy based on the citation-format detected in Step 5:

**author-date mode** (PMB / IOP Harvard):
- pandoc wraps citations in `w:hyperlink` with anchor `ref-{cite_key}`
- the script reads cite_key directly from the anchor — no text matching needed

**numeric mode**:
- pandoc outputs `[1]` or superscripts
- match the mapping directly by number

Run the injection:
```bash
python3 scripts/inject_zotero.py --input OUTDIR/pandoc_output.docx --output OUTDIR/FINAL_zotero.docx \
  --mapping OUTDIR/citation_mapping.json --csl CSL_PATH --user-id USER_ID
```

The script also: deletes the static References section and inserts an `ADDIN ZOTERO_BIBLIOGRAPH` placeholder.

**Verification**:
```bash
python3 -c "import zipfile,re; z=zipfile.ZipFile('OUTPUT.docx'); c=z.open('word/document.xml').read().decode();
  print(f'✓ {len(re.findall(r\"ZOTERO_ITEM CSL_CITATION\", c))} citations');
  print(f'✓ {len(re.findall(r\"ZOTERO_BIBLIOGRAPH\", c))} bibliography')"
```

**Checkpoint**: show the replacement statistics and confirm the counts look reasonable.
