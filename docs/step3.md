# Step 3: 创建 Zotero Collection + 导入已验证文献

仅导入 **PASS** 状态的条目。

## 3a. 新建/复用 Collection

用 `pyzotero` 检查是否已存在同名 collection，不存在则创建。

## 3b. 批量导入

- 有 DOI 的条目：创建 `journalArticle` 模板，只填 DOI，Zotero 自动补全元数据
- 无 DOI 的条目：填入 title、year、authors（从 BIB 解析）。**作者解析规则**：
  - `and others` → 丢弃（不是真实作者）
  - `Last, First` 格式 → 直接拆分
  - `First Last` 格式（无逗号）→ 最后一个词当 lastName，其余当 firstName
  - `{braced name}` → 去掉外层大括号再解析
  - 解析失败 → 跳过该条目并在报告中列出，不阻塞流程

## 3c. 等待同步

`sleep 10`，确认 collection 中条目数。

**检查点**：展示导入报告（已导入数 / 跳过数及原因），等用户确认。

> FAIL/SKIP 不导入——真实性存疑的文献不应污染 Zotero 库。WARN 条目用户可手动导入。
