# Step 2: 依赖检查 + 验证

## 2a. 检查依赖

```bash
python3 -c "from pyzotero import zotero; zot = zotero.Zotero(0, 'user', local=True); print(len(zot.collections()), 'collections')"
pandoc --version | head -1
```

Zotero 未运行则提示启动后重试。

## 2b + 2c. 交叉验证 + 双来源文献真实性核查

统一调用 `scripts/verify_references.py`：

```bash
# 仅交叉验证（快速，默认）
python3 scripts/verify_references.py MD_FILE BIB_FILE

# 交叉验证 + 双来源核查（完整路径）
python3 scripts/verify_references.py MD_FILE BIB_FILE --verify

# 输出 JSON 供后续步骤使用
python3 scripts/verify_references.py MD_FILE BIB_FILE --verify --json OUTDIR/verify_result.json
```

**脚本流程**（`verify_references.py`）：
1. `bibtexparser` 解析 BIB + 正则提取 MD 引用 `[@key]`
2. **交叉验证**：`cross_validate()` — missing_in_bib（致命）、unused_in_md（警告）、no_doi/no_title
3. **双来源核查**（仅 `--verify`）：`dual_verify()` — 对 MD 引用的条目查询 S2 + CrossRef
   - 有 DOI → S2 `paper --id DOI:xxx` + CrossRef `GET /works/{DOI}`
   - 无 DOI → S2 `title-match` + CrossRef `query.title={title}`
4. 对比 title（去标点）、year、第一作者姓氏

**判定规则**：
- ✅ **PASS**：S2 + CR 都找到且信息一致
- ⚠️ **WARN**：都找到但不一致（暂停，展示差异）
- ❌ **FAIL**：至少一源未找到（暂停，必须修正）
- ⏭ **SKIP**：两源均未找到（标记未验证）

**检查点**：脚本输出报告后，致命问题需修复才继续。

> S2 需要 `SEMANTIC_SCHOLAR_API_KEY`，CrossRef 免费。找不到 `s2_api.py` 时降级为 CrossRef 单源并提示。
