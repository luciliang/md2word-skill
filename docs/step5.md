# Step 5: pandoc MD → Word

```bash
pandoc INPUT.md --citeproc --bibliography=REFERENCES.bib --csl=CSL_PATH -o OUTDIR/pandoc_output.docx
```

`CSL_PATH` 由 Step 1 的 `resolve_csl()` 返回。

pandoc 后自动检测 CSL 的 `citation-format`（解析 XML 中 `<category citation-format="...">`）：
- `author-date` → Step 6 用 Author+Year 匹配
- `numeric` → Step 6 用编号匹配
- `note` → Step 6 用脚注标记匹配

**检查点**：pandoc 报错或输出为空时暂停。
