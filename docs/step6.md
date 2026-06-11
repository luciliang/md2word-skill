# Step 6: 注入 Zotero field codes

根据 Step 5 检测的 citation-format 选注入策略：

**author-date 模式**（PMB / IOP Harvard）：
- pandoc 用 `w:hyperlink` 包裹引用，anchor 为 `ref-{cite_key}`
- 脚本自动从 anchor 读取 cite_key，无需文本匹配

**numeric 模式**：
- pandoc 输出 `[1]` 或上标
- 用编号直接匹配 mapping

执行注入：
```bash
python3 scripts/inject_zotero.py --input OUTDIR/pandoc_output.docx --output OUTDIR/FINAL_zotero.docx \
  --mapping OUTDIR/citation_mapping.json --csl CSL_PATH --user-id USER_ID
```

脚本同时：删除静态 References 节，插入 `ADDIN ZOTERO_BIBLIOGRAPH` 占位符。

**验证**：
```bash
python3 -c "import zipfile,re; z=zipfile.ZipFile('OUTPUT.docx'); c=z.open('word/document.xml').read().decode();
  print(f'✓ {len(re.findall(r\"ZOTERO_ITEM CSL_CITATION\", c))} citations');
  print(f'✓ {len(re.findall(r\"ZOTERO_BIBLIOGRAPH\", c))} bibliography')"
```

**检查点**：展示替换统计，确认数量合理。
