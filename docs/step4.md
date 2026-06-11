# Step 4: 构建 cite_key → Zotero item key 映射

从 Step 3 的 collection 中查找（不是全库），用 BIB 的 DOI/title 做桥梁：

```
cite_key → (doi, title) from BIB → match against collection items → Zotero item key
```

匹配优先级：DOI 精确匹配 > 标题去标点后精确匹配。

**检查点**：未匹配列表 > 0 时暂停，等用户决定（手动指定 / 忽略 / 中止）。

保存映射到 `OUTDIR/citation_mapping.json`，格式：`{"cite_key": "ZOTERO_ITEM_KEY", ...}`
