# Step 5: pandoc MD → Word

```bash
pandoc INPUT.md --citeproc --bibliography=REFERENCES.bib --csl=CSL_PATH -o OUTDIR/pandoc_output.docx
```

`CSL_PATH` 默认为本 skill 的 `styles/physics-in-medicine-and-biology.csl`。它是 dependent style，pandoc 会自动在同目录找到 parent `institute-of-physics-harvard.csl`。

pandoc 后自动检测 CSL 的 `citation-format`（解析 XML 中 `<category citation-format="...">`）：
- `author-date` → Step 6 用 Author+Year 匹配
- `numeric` → Step 6 用编号匹配
- `note` → Step 6 用脚注标记匹配

**检查点**：pandoc 报错或输出为空时暂停。
