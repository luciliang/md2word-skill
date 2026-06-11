---
name: md2word-skill
description: "从 Markdown + BibTeX 生成 Zotero 管理的 Word 文档。将 pandoc 引用 [@key] 转为 Zotero CSL_CITATION field codes。触发词: /md2word, md转word, markdown转word, zotero field codes, 参考文献管理, 论文格式化, BibTeX to Word, pandoc to Word, Zotero citation injection."
---

# /md2word: MD + BIB → Zotero-managed Word

## 前提条件

用户必须具备：
- **Markdown 文件**：含 pandoc 风格引用（`[@citekey]` 或 `[@key1; @key2]`）
- **BibTeX 文件**：包含所有引用的参考文献（每条最好有 DOI）
- **Zotero 桌面版**：正在运行（pyzotero 需要本地 API）
- **依赖**：pandoc 2.11+（支持 `--citeproc`）、pyzotero、python-docx、lxml

## 工作流程（6 步）

```
Step 1  收集参数 (md_file, bib_file, collection, csl_style)
Step 2a 检查依赖 (Zotero, pandoc)
Step 2b MD↔BIB 交叉验证 (内部一致性)
Step 2c 双来源文献真实性核查 (S2 + CrossRef)
    ↓
Step 3  创建 Zotero Collection + 导入已验证文献
Step 4  构建 cite_key → Zotero item key 映射
Step 5  pandoc MD → Word (使用指定 CSL 样式)
Step 6  注入 Zotero field codes (根据 CSL 格式自动适配)
```

### Step 1: 收集参数

向用户确认以下信息（如果未提供）：

```
必需：
- md_file:    Markdown 文件路径
- bib_file:   BibTeX 文件路径

可选（有默认值）：
- collection: Zotero collection 名称（默认：BIB 文件名去掉扩展名）
- output:     输出 Word 文件路径（默认：<md文件名>_zotero.docx）
- user_id:    Zotero user ID（默认：3313474）
- csl_style:  CSL 样式名称或路径（默认：physics-in-medicine-and-biology）
```

**CSL 样式解析**：
- 如果用户指定了样式名（如 `physics-in-medicine-and-biology`），先检查 `styles/` 目录下是否有对应 `.csl` 文件
- 如果是 dependent 样式（只含元数据），自动查找其父样式使用
- 如果用户指定了完整路径，直接使用
- 如果用户未指定，默认使用 `physics-in-medicine-and-biology`

```python
import os, re

def resolve_csl(style_name_or_path):
    styles_dir = os.path.expanduser('~/.claude/skills/md2word-skill/styles')
    
    # 用户给了完整路径
    if os.path.isfile(style_name_or_path):
        return style_name_or_path
    
    # 查找 styles/ 目录
    csl_path = os.path.join(styles_dir, f'{style_name_or_path}.csl')
    if not os.path.isfile(csl_path):
        raise FileNotFoundError(f'CSL not found: {csl_path}')
    
    # 检查是否为 dependent 样式（含 independent-parent 链接）
    with open(csl_path) as f:
        content = f.read()
    parent_match = re.search(r'rel="independent-parent"', content)
    
    if parent_match:
        # dependent 样式：找父样式
        parent_id = re.search(r'href="http://www.zotero.org/styles/([^"]+)"\s+rel="independent-parent"', content)
        if parent_id:
            parent_name = parent_id.group(1)
            parent_path = os.path.join(styles_dir, f'{parent_name}.csl')
            if os.path.isfile(parent_path):
                return parent_path
            else:
                raise FileNotFoundError(
                    f'Dependent style "{style_name_or_path}" requires parent "{parent_name}.csl". '
                    f'Download it first:\n'
                    f'curl -sL https://raw.githubusercontent.com/citation-style-language/styles/master/{parent_name}.csl '
                    f'-o {parent_path}')
    
    return csl_path
```

### Step 2: 依赖检查 + 交叉验证

**2a. 检查依赖**：
```bash
python3 -c "from pyzotero import zotero; zot = zotero.Zotero(0, 'user', local=True); print(len(zot.collections()), 'collections')" 2>&1
pandoc --version | head -1
```
Zotero 未运行则提示启动后重试。

**2b. MD ↔ BIB 交叉验证**（在进入 Step 3 之前执行）：

用 MD 的引用和 BIB 的条目做双向校验，提前发现问题：
```python
import bibtexparser, re

def cross_validate(md_path, bib_path):
    # 提取 MD 中所有 [@citekey]
    with open(md_path, encoding='utf-8') as f:
        md_text = f.read()
    md_keys = set(re.findall(r'\[@([\w-]+)', md_text))

    # 提取 BIB 中所有 entry ID
    with open(bib_path, encoding='utf-8') as f:
        db = bibtexparser.load(f)
    bib_keys = {e['ID']: e for e in db.entries}

    # ① 致命：MD 引用了但 BIB 没有 → pandoc 会渲染失败
    missing_in_bib = md_keys - set(bib_keys.keys())

    # ② 警告：BIB 有但 MD 没引用 → 冗余条目
    unused_in_md = set(bib_keys.keys()) - md_keys

    # ③ 信息：匹配上的条目中，缺 DOI 的 → 只能走标题 fallback
    matched = md_keys & set(bib_keys.keys())
    no_doi = [k for k in matched if not bib_keys[k].get('doi', '').strip()]

    # ④ 信息：缺 title 的 → 无法做任何匹配
    no_title = [k for k in matched if not bib_keys[k].get('title', '').strip()]

    return {
        'md_total': len(md_keys),
        'bib_total': len(bib_keys),
        'missing_in_bib': sorted(missing_in_bib),   # 必须修复
        'unused_in_md': sorted(unused_in_md),       # 可选清理
        'no_doi': sorted(no_doi),                   # 走标题 fallback
        'no_title': sorted(no_title),               # 无法匹配
    }
```

**检查点**：展示交叉验证报告——
```
交叉验证报告
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MD 引用数: 50    BIB 条目数: 58
  ✅ 匹配: 48

❌ MD 引用了但 BIB 缺少 (2):     ← 必须修复
   - smith2023missing
   - jones2024typo

⚠️  BIB 有但 MD 未引用 (10):      ← 可选清理
   - ronneberger2015unet, ... 等 10 条

ℹ️  无 DOI 走标题匹配 (36):       ← 提醒
   36/48 匹配条目无 DOI，将走标题 fallback

❌ 无 title 无法匹配 (0)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

- 如果 `missing_in_bib` 不为空 → **暂停，等用户补全 BIB 或修正 cite key**
- 如果 `no_title` 不为空 → **暂停，等用户补全 title**
- 其余情况正常继续

**2c. 双来源文献真实性核查**（交叉验证通过后执行）：

对每条 BIB entry 分别用 **Semantic Scholar** 和 **CrossRef** 独立验证，**两个来源都必须确认**才标记通过。

### 核查策略

对每条 entry，按以下逻辑查询两个来源：

```
来源1: Semantic Scholar
  - 有 DOI → paper --id "DOI:xxx" --fields title,year,authors
  - 无 DOI → title-match --query "title" --fields title,year,authors

来源2: CrossRef
  - 有 DOI → GET https://api.crossref.org/works/{DOI}
  - 无 DOI → GET https://api.crossref.org/works?query.title={title}&rows=1
```

### 通过/失败判定

```
✅ PASS:  两个来源都找到，且信息一致
⚠️  WARN:  两个来源都找到，但信息有不一致（year/author/title）
❌ FAIL:  至少一个来源未找到，或两个来源的信息互相矛盾
⏭  SKIP:  两个来源都未找到（缺 DOI 且 title 太模糊）
```

### 核查代码

```bash
# 来源1: Semantic Scholar（使用 s2_api.py）
uv run scripts/s2_api.py paper \
  --id "DOI:10.1038/s41586-020-2649-2" \
  --fields title,year,authors

# 来源2: CrossRef（直接 curl，无需 API key）
curl -s "https://api.crossref.org/works/10.1038/s41586-020-2649-2" \
  | python3 -c "import sys,json; d=json.load(sys.stdin)['message'];
    print(json.dumps({'title': d.get('title',[''])[0],
                      'year': d.get('published-print',d.get('published-online',{})).get('date-parts',[[None]])[0][0],
                      'authors': [a.get('family','') for a in d.get('author',[])]}))"
```

```python
def dual_verify(bib_entry, s2_result, crossref_result):
    """双来源交叉核对，返回 (status, issues)"""
    issues = []
    s2_ok = s2_result is not None
    cr_ok = crossref_result is not None
    bib_title = re.sub(r'[^\w]', '', bib_entry.get('title', '')).lower()
    bib_year = bib_entry.get('year', '')

    def normalize(t):
        return re.sub(r'[^\w]', '', t).lower() if t else ''

    # 来源1核对
    s2_issues = []
    if s2_ok:
        if normalize(s2_result.get('title', '')) != bib_title:
            s2_issues.append(f"S2 title mismatch")
        s2_year = str(s2_result.get('year', ''))
        if bib_year and s2_year and s2_year != bib_year:
            s2_issues.append(f"S2 year: {s2_year} vs BIB: {bib_year}")
    else:
        s2_issues.append("S2: 未找到")

    # 来源2核对
    cr_issues = []
    if cr_ok:
        if normalize(crossref_result.get('title', '')) != bib_title:
            cr_issues.append(f"CR title mismatch")
        cr_year = str(crossref_result.get('year', ''))
        if bib_year and cr_year and cr_year != 'None' and cr_year != bib_year:
            cr_issues.append(f"CR year: {cr_year} vs BIB: {bib_year}")
    else:
        cr_issues.append("CR: 未找到")

    # 双来源判定
    if not s2_ok and not cr_ok:
        return 'SKIP', ['两个来源均未找到']
    if not s2_ok or not cr_ok:
        return 'FAIL', s2_issues + cr_issues  # 单源确认不够
    if s2_issues or cr_issues:
        return 'WARN', s2_issues + cr_issues  # 都找到但不一致
    return 'PASS', []
```

### 检查点：展示核查报告

```
双来源文献真实性核查报告
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  核查条目: 50    ✅ PASS: 40    ⚠️ WARN: 5    ❌ FAIL: 2    ⏭ SKIP: 3

❌ FAIL - 至少一个来源未确认 (2):       ← 必须修正
   - smith2023fake: S2未找到, CR未找到
   - jones2024typo: S2未找到, CR year=2023 vs BIB=2024

⚠️  WARN - 信息不一致 (5):              ← 需人工确认
   - kendall2017: S2 year=2017✓, CR year=2018✗
   - gal2016: S2 author=Gal✓, CR author=Ghahramani✗
   - wang2020: S2 title轻微差异, CR title一致
   ...

⏭  SKIP - 两个来源均未找到 (3):          ← 无法验证
   - someref2024, anotherref2023, oldref2001
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

- **FAIL** → **暂停，必须修正或删除后才能继续**
- **WARN** → **暂停，展示具体差异，等用户逐条确认**
- **SKIP** → 正常继续，标记为未验证
- **PASS** → 自动继续

> **为什么需要双来源**：单一来源可能覆盖不全（S2 偏 CS，CrossRef 偏期刊/书籍），或本身数据有错。两个独立来源都确认，才能可靠判断文献真实存在且信息无误。
> Semantic Scholar API 需要 `SEMANTIC_SCHOLAR_API_KEY`，CrossRef API 免费无需 key。
### Step 3: 创建 Zotero Collection + 导入已验证文献

Step 2c 双来源核查通过后，只将 **PASS** 状态的文献导入 Zotero。

**3a. 新建 Collection**：
```python
from pyzotero import zotero
zot = zotero.Zotero(0, 'user', local=True)

# 检查是否已存在同名 collection
collections = zot.collections()
target_key = None
for c in collections:
    if c['data']['name'] == COLLECTION_NAME:
        target_key = c['key']
        break

if not target_key:
    # 创建新 collection
    resp = zot.create_collection({'name': COLLECTION_NAME})
    target_key = resp['successful']['0']['key']
    print(f'✅ 已创建 collection: {COLLECTION_NAME} (key={target_key})')
else:
    print(f'ℹ️  collection 已存在: {COLLECTION_NAME} (key={target_key})')
```

**3b. 导入已验证文献**（仅 PASS 条目）：

用 pyzotero 批量创建条目，优先使用 DOI（Zotero 会自动补全元数据）：
```python
def import_verified(bib_entries, verify_results, collection_key):
    """将双来源核查通过的 BIB 条目导入 Zotero collection"""
    imported = []
    skipped = []

    for entry in bib_entries:
        cite_key = entry['ID']
        status = verify_results.get(cite_key, {}).get('status')

        # 仅导入 PASS 的条目
        if status != 'PASS':
            skipped.append(f"{cite_key} ({status})")
            continue

        doi = entry.get('doi', '').strip()
        title = entry.get('title', '').strip()

        # 优先用 DOI：Zotero 会自动通过 DOI 补全所有字段
        if doi:
            template = zot.item_template('journalArticle')
            template['DOI'] = doi
            template['title'] = title  # fallback 显示
            template['creators'] = []  # DOI 会自动填充
        else:
            # 无 DOI：用标题创建，手动填入 BIB 中的元数据
            template = zot.item_template('journalArticle')
            template['title'] = title
            template['date'] = entry.get('year', '')
            # 解析作者
            for author_str in entry.get('author', '').split(' and '):
                parts = author_str.strip().split(',')
                if len(parts) >= 2:
                    template['creators'].append({
                        'creatorType': 'author',
                        'lastName': parts[0].strip(),
                        'firstName': parts[1].strip()
                    })
                elif parts[0].strip():
                    template['creators'].append({
                        'creatorType': 'author',
                        'name': parts[0].strip()
                    })

        resp = zot.create_items([template])
        if resp.get('successful'):
            item_key = resp['successful']['0']['key']
            zot.addto_collection(item_key, collection_key)
            imported.append(cite_key)
        else:
            skipped.append(f"{cite_key} (导入失败)")

    return imported, skipped
```

**3c. 等待 Zotero 同步**：
```bash
# Zotero 需要时间处理 DOI 并补全元数据
sleep 10
# 确认 collection 中的条目数
python3 -c "
from pyzotero import zotero
zot = zotero.Zotero(0, 'user', local=True)
items = zot.collection_items('{target_key}')
print(f'collection 中条目数: {len(items)}')
"
```

**检查点**：展示导入报告——
```
文献导入报告
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  已导入: 45    跳过: 5 (WARN/FAIL/SKIP)

  ✅ 已导入 (45):
     isensee2018nnunet, ronneberger2015unet, kendall2017uncertainties, ...

  ⏭ 跳过 (5):
     - wahid2024aiuq (SKIP - 两源均未找到)
     - smith2023fake (FAIL - 文献不存在)
     - ...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**用户确认**：确认导入数量和跳过列表是否合理。确认后继续。

> **为什么只导入 PASS 条目**：FAIL/SKIP 的文献真实性存疑，导入 Zotero 会污染文献库。用户可在 WARN 条目中选择性手动导入。

### Step 4: 构建 cite_key → Zotero item key 映射

从 Step 3 创建的 collection 中查找条目，不需要全库搜索：

```python
def build_mapping(md_path, bib_path, collection_key):
    import bibtexparser, re
    from pyzotero import zotero

    zot = zotero.Zotero(0, 'user', local=True)

    # 从 MD 提取引用顺序
    with open(md_path, encoding='utf-8') as f:
        md_text = f.read()
    cite_keys = re.findall(r'\[@([\w-]+)', md_text)
    # 按首次出现顺序编号，去重
    seen = {}
    for ck in cite_keys:
        if ck not in seen:
            seen[ck] = len(seen) + 1

    # 从 collection 中获取所有条目
    items = zot.collection_items(collection_key)

    # 用 BIB 文件的 DOI/title 做桥梁：cite_key → (doi, title) → Zotero item
    with open(bib_path, encoding='utf-8') as f:
        db = bibtexparser.load(f)
    bib_map = {e['ID']: {'doi': e.get('doi','').strip(), 'title': e.get('title','').strip()} for e in db.entries}

    mapping = {}
    unmatched = []
    for ck, pandoc_num in seen.items():
        bib_info = bib_map.get(ck, {})
        found = False

        # 优先 DOI 精确匹配
        if bib_info.get('doi'):
            for item in items:
                item_doi = item['data'].get('DOI', '').strip().lower()
                if item_doi == bib_info['doi'].lower():
                    mapping[str(pandoc_num)] = item['key']
                    found = True
                    break

        # fallback: 标题模糊匹配
        if not found and bib_info.get('title'):
            norm_bib = re.sub(r'[^\w]', '', bib_info['title']).lower()
            for item in items:
                norm_zot = re.sub(r'[^\w]', '', item['data'].get('title', '')).lower()
                if norm_bib == norm_zot:
                    mapping[str(pandoc_num)] = item['key']
                    found = True
                    break

        if not found:
            unmatched.append(ck)

    return mapping, unmatched
```

2. **检查点**：输出未匹配的 cite_key 列表。
   - 如果未匹配数 > 0：**暂停，展示未匹配列表，等用户决定**（手动指定 / 忽略 / 中止）
   - 如果全部匹配：继续

保存映射到临时 JSON 文件供脚本使用。格式：`{"1": "J8K6WXE8", "2": "7SU3QAU9", ...}`

### Step 5: pandoc MD → Word

**使用 Step 1 中解析的 CSL 样式文件**：
```bash
pandoc INPUT.md \
  --citeproc \
  --bibliography=REFERENCES.bib \
  --csl=CSL_PATH \
  -o /tmp/pandoc_output.docx
```

`CSL_PATH` 由 `resolve_csl(csl_style)` 返回，已处理 dependent → parent 解析。

**当前已安装的 CSL 样式**（`styles/` 目录）：

| 文件 | 格式类型 | 适用场景 |
|------|---------|----------|
| `physics-in-medicine-and-biology.csl` | author-date (dependent) | PMB 期刊，依赖 IOP Harvard |
| `institute-of-physics-harvard.csl` | author-date | IOP 系列期刊父样式 |

添加新样式：
```bash
# 从 Zotero CSL 仓库下载
curl -sL https://raw.githubusercontent.com/citation-style-language/styles/master/<style-name>.csl \
  -o ~/.claude/skills/md2word-skill/styles/<style-name>.csl
```

**检查点**：如果 pandoc 报错或输出文件为空，**暂停展示错误信息，等用户决定**。

pandoc 输出后，自动检测 CSL 的 citation-format 并记录，供 Step 6 使用：
```python
import xml.etree.ElementTree as ET

def get_csl_format(csl_path):
    """从 CSL 文件读取 citation-format 类型"""
    tree = ET.parse(csl_path)
    root = tree.getroot()
    ns = {'csl': 'http://purl.org/net/xbiblio/csl'}
    for cat in root.findall('.//csl:category', ns):
        fmt = cat.get('citation-format')
        if fmt:
            return fmt  # 'author-date', 'numeric', 'label', 'note'
    return 'author-date'  # 默认
```

将检测到的格式类型传递给 Step 6，决定注入策略。
### Step 6: 注入 Zotero field codes

**根据 Step 5 检测到的 citation-format 自动选择注入策略**：

| citation-format | pandoc 输出 | 注入方式 |
|-----------------|------------|----------|
| `author-date` | `(Kendall and Gal 2017)` | 匹配 Author+Year 文本 → 替换为 field code |
| `numeric` | `[1]` 或上标 `¹` | 匹配编号文本 → 替换为 field code |
| `note` | 脚注引用 | 匹配脚注标记 → 替换为 field code |

**6a. 解析 pandoc 输出的引用文本**：

以 `author-date` 为例（PMB / IOP Harvard 格式）：

```python
def extract_author_year_citations(docx_path, bib_path):
    """从 Word 中提取著者-出版年引用，匹配回 cite_key"""
    import bibtexparser, re
    from docx import Document

    doc = Document(docx_path)
    
    # 构建 cite_key → (authors_str, year) 的查找表
    with open(bib_path, encoding='utf-8') as f:
        db = bibtexparser.load(f)
    
    bib_lookup = {}
    for entry in db.entries:
        year = entry.get('year', '')
        authors = []
        for a in entry.get('author', '').split(' and '):
            parts = a.strip().split(',')
            authors.append(parts[0].strip())  # 取姓氏
        bib_lookup[entry['ID']] = {
            'authors': authors,
            'year': year,
            'display': f"{', '.join(authors[:2])}{' et al' if len(authors) > 2 else ''}, {year}"
        }
    
    # 在 Word 中查找引用块
    # IOP Harvard 格式：
    #   (Harman et al 2008)  ← 括号引用，无逗号
    #   Harman et al (2008)   ← 叙述引用
    #   (Author1 2020; Author2 2021) — 多引用
    citations = []
    for para in doc.paragraphs:
        # 括号引用: (...)
        for m in re.finditer(r'\(([^)]+\d{4}[^)]*)\)', para.text):
            citations.append(m.group(1))
        # 叙述引用: Author (Year)
        for m in re.finditer(r'([A-Z][a-zA-Z\s&]+?)\s*\((\d{4})\)', para.text):
            citations.append(f"{m.group(1)}, {m.group(2)}")
    
    # 匹配回 cite_key
    matched = {}
    for cite_text in citations:
        for ck, info in bib_lookup.items():
            # 检查引用文本是否包含该条目的作者+年份
            for author in info['authors']:
                if author in cite_text and info['year'] in cite_text:
                    matched[cite_text] = ck
                    break
    
    return matched
```

**6b. 注入 Zotero CSL_CITATION field codes**：

对每个匹配到的引用，用 Zotero item key 构建 `ADDIN CSL_CITATION` field code：
```bash
python3 ~/.claude/skills/md2word-skill/scripts/inject_zotero.py \
  --input /tmp/pandoc_output.docx \
  --output FINAL_OUTPUT.docx \
  --mapping /tmp/citation_mapping.json \
  --user-id ZOTERO_USER_ID \
  --format author-year
```

`--format` 参数由 Step 5 检测到的 `citation-format` 决定（`author-year` / `numeric` / `note`）。
脚本将文本引用替换为 Zotero 原生的 `ADDIN CSL_CITATION` field code，
删除静态 References 节，插入 `ADDIN ZOTERO_BIBLIOGRAPH` 占位符。

**用户确认点**：脚本运行后，展示替换统计（多少引用被替换、多少警告），确认数量是否合理。

### 验证

```bash
python3 -c "
from docx import Document
import zipfile, re
with zipfile.ZipFile('OUTPUT.docx') as z:
    content = z.open('word/document.xml').read().decode()
    citations = re.findall(r'ZOTERO_ITEM CSL_CITATION', content)
    bibs = re.findall(r'ZOTERO_BIBLIOGRAPH', content)
    print(f'✓ {len(citations)} Zotero citation fields')
    print(f'✓ {len(bibs)} bibliography placeholder')
"
```

最终在 Word 中打开输出文件，Zotero 插件应自动识别 field codes 并管理引用。
文内引用格式由 CSL 样式决定（PMB 为 author-date），参考文献列表由 Zotero 自动生成。
## 注意事项

- **不要覆盖**现有文件，输出总是写到新路径
- **不要修改**现有 Zotero collection，除非用户明确要求
- 如果 BIB 中有条目在 Zotero 中找不到匹配，**暂停并报告**未匹配列表
- pandoc 版本需支持 `--citeproc`（pandoc 2.11+）
- 如果用户已有 Word 文件（不需要从 MD 转换），只需执行 Step 4（构建映射）和 Step 6（注入），跳过 pandoc
- CSL 样式文件是工作流的核心——它决定了文内引用格式、参考文献列表格式，以及 Step 6 的注入策略

## 边界条件与异常处理

| 情况 | 处理方式 |
|------|----------|
| BIB 文件编码非 UTF-8 | 用 `iconv -f GBK -t UTF-8` 转码后再解析 |
| MD 中没有引用标记 `[@key]` | 跳过 Step 4-6，仅做 pandoc 转换 |
| Zotero collection 为空 | 提示用户先导入，暂停等待 |
| 同一 cite_key 在 BIB 中重复 | 取最后一条，并在未匹配报告中标注 |
| BIB 条目无 DOI 也无 title | 无法匹配，列入未匹配报告让用户手动指定 |
| CSL 是 dependent 样式 | 自动查找父样式，找不到则报错并给出下载命令 |
| 用户指定的 CSL 不存在 | 列出 styles/ 目录下已有样式，提示用户选择或下载 |
| Zotero item key 映射不完整 | 脚本会跳过未映射的引用并输出警告 |
