---
name: md2word-skill
description: "Generate Zotero-managed Word documents from Markdown + BibTeX. Converts pandoc citations [@key] into Zotero CSL_CITATION field codes. Triggers: /md2word, md转word, markdown转word, markdown to word, BibTeX to Word, pandoc to Word, zotero field codes, 参考文献管理, 论文格式化, Zotero citation injection."
---

# /md2word: MD + BIB → Zotero-managed Word

## Prerequisites

- **Markdown file**: contains pandoc-style citations (`[@key]` or `[@key1; @key2]`)
- **BibTeX file**: contains all referenced entries (preferably with DOI each)
- **Zotero desktop**: running. Reads use the Local API; **imports/writes must use the Web API** (`ZOTERO_API_KEY` + `ZOTERO_USER_ID` — the Local API does not support writes)
- **Dependencies**: pandoc 2.11+ (`--citeproc`), pyzotero, python-docx, lxml, bibtexparser; three-source verification uses CrossRef + PubMed + OpenAlex (all free, no key)
- **Bundled CSL styles**: the `styles/` directory ships `physics-in-medicine-and-biology.csl` (dependent) and `institute-of-physics-harvard.csl` (parent). The former is used by default; when the user specifies another style, they must provide a path or URL.

## Workflow

> **Output convention**: all intermediate files and the final output are saved to the same directory as the MD and BIB files (referred to below as `OUTDIR`) unless the user specifies otherwise. Final filename: `<md_filename>_zotero.docx`.

> **Execution convention**: each step **must run on its own** and print its progress and results to the terminal before moving to the next. Never merge multiple steps into a single silent command. Before each step, use `echo` or `print` to show the current step number and goal.

```
Fast path (default):    Step 1 → 2a+2b → 3 → 4 → 5 → 6          ≈ 40s
Full path (--verify):   Step 1 → 2a+2b+2c → 3 → 4 → 5 → 6        ≈ 100-180s
```

- **Fast path**: skips Step 2c (three-source verification) and imports directly. Suitable when BIB quality is trusted.
- **Full path**: runs the CrossRef + PubMed + OpenAlex three-source verification and imports authoritative metadata (correcting BIB errors). Suitable for pre-submission final review.
- When the user does not specify, **default to the fast path**.
- When the user says "verify / check references / verify", take the full path.

| Step | Description | Details |
|------|-------------|---------|
| 1 | Collect parameters & environment check | `docs/step1.md` |
| 2 | Dependency check + cross-validation [+ three-source verification & arbitration] | `docs/step2.md` |
| 3 | Create Collection + import authoritative metadata | `docs/step3.md` |
| 4 | Mapping (produced by import, with confidence/audit) | `docs/step4.md` |
| 5 | pandoc MD → Word | `docs/step5.md` |
| 6 | Inject Zotero field codes | `docs/step6.md` |

> **Progressive reading**: load `docs/step-N.md` only when execution reaches that step; do not load everything at once.

---

## Notes

- **Do not overwrite** existing files; write outputs to a new path
- **Do not modify** existing Zotero collections unless the user explicitly asks
- pandoc requires 2.11+ (supports `--citeproc`)
- If a Word file already exists and only needs injection → skip Step 5, go straight to Step 4+6
- CSL is the core of the workflow — it drives citation format, reference-list format, and injection strategy
- **Import authoritative metadata, do not trust the BIB**: Step 3 uses the CrossRef/PubMed/OpenAlex data adjudicated by verify (correcting author names, years, etc. in the BIB). ⚠️ Do not use "fill only the DOI and let Zotero auto-complete" — pyzotero (Local/Web API) does not trigger auto-completion; in practice this yields incomplete entries with only a DOI

## Edge cases

| Case | Handling |
|------|----------|
| BIB not UTF-8 | `iconv -f GBK -t UTF-8` to transcode |
| MD has no citation markers | skip Step 4-6, pandoc conversion only |
| Collection is empty | prompt the user to import first, pause |
| Duplicate cite_key | take the last one, flag it in the report |
| Entry has neither DOI nor title | cannot match, report and ask the user to specify |
| CSL is dependent | auto-resolve the parent style; report an error if not found |
| CSL missing | list available styles, prompt to download |
| Mapping incomplete | skip unmapped citations, output a warning |
