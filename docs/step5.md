# Step 5: pandoc MD → Word

```bash
pandoc INPUT.md --citeproc -M link-citations=true --bibliography=REFERENCES.bib --csl=CSL_PATH -o OUTDIR/pandoc_output.docx
```

`CSL_PATH` defaults to this skill's `styles/physics-in-medicine-and-biology.csl`. It is a dependent style; pandoc finds the parent `institute-of-physics-harvard.csl` in the same directory automatically.

> **`-M link-citations=true` is mandatory**: it makes pandoc render citations as `<w:hyperlink w:anchor="ref-{cite_key}">`. Step 6's inject uses this anchor to **precisely** locate cite_key (distinguishing multiple works by the same author in the same year). If omitted, inject falls back to text matching, and same-year-same-author references get mis-associated.

After pandoc, auto-detect the CSL's `citation-format` (parse `<category citation-format="...">` from the XML):
- `author-date` → Step 6 uses Author+Year matching
- `numeric` → Step 6 matches by number
- `note` → Step 6 matches by footnote marker

**Checkpoint**: pause if pandoc errors or the output is empty.
