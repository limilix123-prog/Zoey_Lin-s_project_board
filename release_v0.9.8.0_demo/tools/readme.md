# tools/

workspace 工程工具集,跟 `project_board/` 同级。住"工程治理 / 扫漏 / 格式检查"类工具,跟项目业务代码隔离。

## code_cleanliness_check.py

扫 `.py` 文件,检 5 条清洁度规则。

### 5 条规则

| # | 规则 | 阈值 | 报告形式 |
|---|------|------|----------|
| 1 | `file_too_long` | 文件总行数 > 1000 | `file_too_long: path N lines` |
| 2 | `function_too_long` | 函数/方法体行数 > 200 | `function_too_long: path:start-end name=... body=N lines` |
| 3 | `docstring_style_mixed` | 同一文件混用 `''' '''` 和 `"""` 两种 docstring 引号 | `docstring_style_mixed: path form_a=... count_a=N form_b=... count_b=M` |
| 4 | `comment_block_too_long` | 连续 `#` 注释 > 5 行 | `comment_block_too_long: path:start-end N consecutive` |
| 5 | `line_too_long` | 源码行字符数(去 trailing whitespace) > 128 | `line_too_long: path:line N chars` |

#### Rule 2 细节
- 用 `ast` 解析,函数体行数 = `end_lineno - lineno`(含 def 行下一行到函数块末行)
- 包括 `def` / `async def` / 嵌套函数 / 类方法
- module 顶部 docstring 不算函数

#### Rule 3 细节
- 同一文件内 docstring 引号风格必须**唯一**(全 `''' '''` 或全 `"""`,不强制哪种)
- 函数缺 docstring **不**算违规;只关心**实际出现**的引号形式
- 集合 = 0(无 docstring)或 集合 = 1(全一种)→ 不报;集合 > 1 → 报 `docstring_style_mixed`
- module 顶部 docstring 同样算入集合
- 报告字段:每种引号各出现几次(`form_a` / `count_a` / `form_b` / `count_b`)
- 不把 type annotation(`: str` 等)误判为 docstring — AST 区分 `Expr(Constant(str))` 和 `AnnAssign`

#### Rule 4 细节
- 5 行连续 OK,6 行 fail
- 注释块之间空行打断连续
- 跳过 docstring 内部的 `#` 字符(那是 docstring 内容,不是源码注释)

#### Rule 5 细节
- 默认阈值 **128 字符**(含),用 `line.rstrip()` 后再 `len()` 算字符数(trailing whitespace 不算)
- 跳过 **string literal 内部的所有行**(`''' '''` / `"""..."""` docstring、`'...'` / `"..."` 字符串、多行 raw / f-string) — 用 `tokenize` 标 STRING token 跨行范围,而不是 ad-hoc 引号计数
- 空行 / 全空白行(字符数 = 0)不算违规
- 一行超长报一条;一个文件可能报多条
- 阈值可调:`--max-line-chars N` CLI flag(默认 128)
- 一个文件可能因该行在 comment block 末尾同时被 Rule 4 + Rule 5 报,这是预期(规则正交,违规也是正交)

### CLI

```bash
python tools/code_cleanliness_check.py                         # 扫 <workspace>/project_board/
python tools/code_cleanliness_check.py --path <file_or_dir>    # 自定义路径
python tools/code_cleanliness_check.py --strict                # 有违规 → exit 1
python tools/code_cleanliness_check.py --json                  # JSON 格式(机器可读)
python tools/code_cleanliness_check.py --quiet                 # 只打违规总数
python tools/code_cleanliness_check.py --max-line-chars 100    # Rule 5 阈值改 100
```

### 示例输出(人类可读)

```
[FAIL] file_too_long: project_board/foo/bar.py 1234 lines
[FAIL] function_too_long: project_board/foo/baz.py:45-300 name=big_func body=256 lines
[FAIL] docstring_style_mixed: project_board/foo/q.py form_a=''' count_a=2 form_b=""" count_b=1
[FAIL] comment_block_too_long: project_board/foo/p.py:30-40 11 consecutive
[FAIL] line_too_long: project_board/foo/long.py:42 184 chars

TOTAL: 5 violations in 5 files
```

### 示例输出(JSON)

```json
[
  {"rule": "file_too_long", "path": "...", "lines": 1234},
  {"rule": "function_too_long", "path": "...", "start": 45, "end": 300, "name": "big_func", "body_lines": 256},
  {"rule": "docstring_style_mixed", "path": "...", "form_a": "'''", "count_a": 2, "form_b": "\"\"\"", "count_b": 1},
  {"rule": "comment_block_too_long", "path": "...", "start": 30, "end": 40, "count": 11},
  {"rule": "line_too_long", "path": "...", "line": 42, "chars": 184}
]
```

### 实现要点

- **stdlib only**:`argparse` / `ast` / `io` / `json` / `logging` / `pathlib` / `sys` / `tokenize`,无任何第三方依赖
- 函数体行数用 AST 节点 `lineno` / `end_lineno`,不是正则
- docstring form 检查源码第一行引号字符(看 delimiter),不是 AST 常量值
- 注释连续行扫描跳过 docstring 内部行
- Rule 5 用 `tokenize.generate_tokens` 标 STRING token 跨行范围,而不是引号计数(避免多行字符串 + 注释里出现 `'` 误判)
- 工具本身守自己的规则(行数 < 1000,函数 < 200,docstring 引号风格一致(全 `''' '''`),注释块 < 5,每行 < 128 字符)

### Regression 测试

`_test_violations.py` 是故意构造的违规样例,5 条规则各至少触发 1 次。改完工具先跑这个文件验证 5 规则都还工作,再扫真项目。

## cleanword_check.py

扫 `.py` 文件,检 7 条"语言/语义冗余"规则:同义反复、空模板、word spam、套话前缀、公式化开头、重复句子、噪音词。补充 cleancode 工具的"形式清洁度"维度,加一层"语义清洁度"。

### 7 条规则

| # | 规则 | 触发条件 | 报告形式 |
|---|------|----------|----------|
| 1 | `tautology` | 行是 `X = X` / `X 即 X` / `X means X` / `X 就是 X`,两边是同一 word | `tautology: path:line line=... pattern=1` |
| 2 | `empty_template` | 行是 `PLACEHOLDER -> PLACEHOLDER`,两侧 ALL_CAPS | `empty_template: path:line line=... pattern=2` |
| 3 | `word_spam` | 单行文本里某 word 出现 ≥ 4 次 | `word_spam: path:line word=... count=N pattern=3` |
| 4 | `cliche_prefix` | 行以中文套话开头("重要的是"/"非常"/"基本上"/"实际上"/"应该说" 等),且行短 | `cliche_prefix: path:line prefix=... pattern=4` |
| 5 | `formulaic_opener` | 行以公式化开头("在这里"/"在这种情况下"/"首先"/"其次"/"最后"/"综上所述" 等),且行短 | `formulaic_opener: path:line opener=... pattern=5` |
| 6 | `repeated_sentence` | 相邻两行文本 ratio ≥ 0.85(diffflib 自动 junk 关闭) | `repeated_sentence: path:line match_line=N ratio=R pattern=6` |
| 7 | `filler_words` | 单行文本里虚词(的/了/和/是/在 + the/is/of/...)占比 > 0.50,且总词数 ≥ 8 | `filler_words: path:line hits=N total=M ratio=R pattern=7` |

#### Rule 1 细节
- 末尾标点限定为 `[:.;)]?`(不含 `,`),排除 `render_template("x.html", storage=storage,)` 这类 kwargs
- docstring 包裹 (`"""foo = foo"""`) 和行尾注释 (`foo = foo  # note`) 都被剥离后再匹配
- 同一 word 用 backref 验证 (`\1`),不是字面量

#### Rule 2 细节
- 两侧必须是 `[A-Z][A-Z0-9_]{1,}` 或 `[A-Z_]{2,}`(纯大写,至少 2 字符)
- 箭头: `->` / `→` / `=>` / `⟶`
- 类型注解 `-> int` (右侧小写) 不触发

#### Rule 3 细节
- min count = 4(避免英文正常注释里 "the" / "a" 出现 3 次的误报)
- min len = 1(中文单字 的是合法 word)
- CJK 字符按**逐字符**切分(中文无空格分词);ASCII 按 `[A-Za-z0-9_]+` 切分
- 仅查 STRING (docstring + standalone string expr) + COMMENT 行,代码行不查
- 多行 STRING 的 start_line 一次性分析整段,internal lines 跳过

#### Rule 4 / 5 细节
- 用 `_violation_body(line)` 提取"violation-relevant 内容":剥离行尾 `#` 注释 + 提取单行 docstring 内部
- 长度 cap 30 chars(行 body 长度,不算注释)
- words[0] 不再用作判断(因为 CJK 切分后 words[0] 可能是英文注释词)
- 改为 `body.startswith(prefix)` 直接判

#### Rule 6 细节
- 仅查 STRING/COMMENT 文本行,代码行不查
- 多行 docstring 内部行 + 连续 `#` 注释 block 内部行都跳过
- 用 `difflib.SequenceMatcher(ratio, autojunk=False)`
- 报告第一行;匹配的第二行作为新 anchor,继续检查下一行

#### Rule 7 细节
- FILLER_WORD_RATIO = 0.50(高阈值,避免英文正常注释里 ~30% 虚词误报)
- FILLER_WORD_MIN_WORDS = 8(短行不查)
- 中文虚词: 的/了/和/是/在/有/就/也/都/与
- 英文虚词: the/is/of/and/to/in/a/an/for/on/at/by/as/or/be/this/that/it/with

#### 通用: "text 行" 分类
工具用 AST 识别"docstring / 独立 string expr statement" + tokenize 标 COMMENT:
- **text 行** = 任何 `Expr(Constant(str))` 节点覆盖的行 (docstring + 独立 string expr statement) + COMMENT 行
- **internal_text_lines** = 多行 docstring 内部行 + 连续 `#` 注释 block 内部行(这些行的 text-only rules 都跳过,避免 docstring/注释块被切碎成 N 个独立 sentence)
- 排除 `foo = "x"` / `print("x")` / tuple member (`_CLICHE_PREFIXES = ("重要的是", ...)`) 等 literal in code(用 AST 区分 expr statement vs assignment RHS)

### CLI

```bash
python tools/cleanword_check.py                                # 默认扫 <workspace>/project_board/
python tools/cleanword_check.py --path <file_or_dir>           # 自定义路径
python tools/cleanword_check.py --strict                       # 有违规 → exit 1
python tools/cleanword_check.py --json                         # JSON 格式(机器可读)
python tools/cleanword_check.py --quiet                        # 只打违规总数
python tools/cleanword_check.py --delete --backup              # 真删违规行(备份到 .bak,不带 --backup 拒绝执行)
```

### 示例输出(人类可读)

```
[FAIL] tautology: project_board/foo.py:42 line='foo = foo' pattern=1
[FAIL] empty_template: project_board/foo.py:100 line='FOO -> BAR' pattern=2
[FAIL] word_spam: project_board/foo.py:55 word='the' count=10 pattern=3
[FAIL] cliche_prefix: project_board/foo.py:60 prefix='重要的是' pattern=4
[FAIL] formulaic_opener: project_board/foo.py:65 opener='首先' pattern=5
[FAIL] repeated_sentence: project_board/foo.py:70 match_line=71 ratio=0.946 pattern=6
[FAIL] filler_words: project_board/foo.py:80 hits=10 total=14 ratio=0.714 pattern=7

TOTAL: 7 violations in 3 files
BY_RULE: cliche_prefix=1, empty_template=1, filler_words=1, formulaic_opener=1, repeated_sentence=1, tautology=1, word_spam=1
```

### 示例输出(JSON)

```json
[
  {"rule": "tautology", "path": "project_board/foo.py", "line": 42, "text": "foo = foo", "pattern": 1},
  {"rule": "empty_template", "path": "project_board/foo.py", "line": 100, "text": "FOO -> BAR", "pattern": 2},
  {"rule": "word_spam", "path": "project_board/foo.py", "line": 55, "word": "the", "count": 10, "pattern": 3},
  {"rule": "cliche_prefix", "path": "project_board/foo.py", "line": 60, "prefix": "重要的是", "pattern": 4},
  {"rule": "formulaic_opener", "path": "project_board/foo.py", "line": 65, "opener": "首先", "pattern": 5},
  {"rule": "repeated_sentence", "path": "project_board/foo.py", "line": 70, "match_line": 71, "ratio": 0.946, "pattern": 6},
  {"rule": "filler_words", "path": "project_board/foo.py", "line": 80, "hits": 10, "total": 14, "ratio": 0.714, "pattern": 7}
]
```

### 实现要点

- **stdlib only**:`argparse` / `ast` / `difflib` / `io` / `json` / `logging` / `pathlib` / `re` / `sys` / `tokenize`,无任何第三方依赖
- "text 行" 分类用 AST(`Expr(Constant(str))` 节点,包括 docstring + 独立 string expr statement)而非 tokenize 单独看(避免 `foo = "..."` literal 误报)
- CJK word 切分按"逐字符"(中文无空格),ASCII 按 `[A-Za-z0-9_]+` 切分
- multi-line STRING (docstring) 内部行 + 连续 `#` 注释 block 内部行都被标记 `internal_text_lines`,text-only rules 跳过,避免误报
- `_violation_body(line)` 提取"行内 violation-relevant 内容"(剥离行尾 `#` 注释 + 单行 docstring 内部)
- 工具本身守自己的规则(行数 < 1000,函数 < 200,docstring 引号风格一致(全 `''' '''`),注释块 < 5,每行 < 128 字符)
- 工具本身跑自己 0 假报(自检通过)

### Regression 测试

`_test_violations_cleanword.py` 是故意构造的违规样例,7 条规则各至少触发 1 次(实际 19 个 violations,7 模式都覆盖,中文 + 英文 + 中英混排都有 case)。改完工具先跑这个文件验证 7 规则都还工作,再扫真项目。

## gen_module_feature_index.py

扫 `project_board/<module>/` 目录,生成"模块 × 特性"目录的 markdown 表格,供 `project_board/readme.md` 的 `## 模块-特性目录` 段用。

### 行为

- 扫 `project_root` 立即子目录(跳 dunder / hidden / 非 dir),每个子目录 = 一行
- "职责" 抽取优先级(每条都只取**第一行非空 prose**):
  1. `<module>/readme.md` 第二段(以 `# <module>` 开头段后的下一段非标题段)
  2. fallback: `<module>/__init__.py` 顶部 docstring
  3. 都缺: 写 `(无职责描述)` + stderr warn
- 特性列表: `<module>/feature_*.py` 的 stem(去掉 `.py`),按名字 lex 排序
- 9 个模块,每行输出 `模块 | 职责 | 特性数 | 特性列表`

### CLI

```bash
python tools/gen_module_feature_index.py                                # markdown 表格到 stdout
python tools/gen_module_feature_index.py --module projects               # 只显示 projects 模块
python tools/gen_module_feature_index.py --json                          # JSON 格式到 stdout
python tools/gen_module_feature_index.py --write                         # 写回 project_board/readme.md ## 模块-特性目录 段
python tools/gen_module_feature_index.py --write --backup                # 写前 cp readme 到 history/project_board_v081_pre_readme/
python tools/gen_module_feature_index.py --module projects --json        # 单模块 JSON
```

### 示例输出(默认 markdown 表格)

```
| 模块 | 职责 | 特性数 | 特性列表 |
|---|---|---|---|
| accounts | User 数据模型 + 密码 hash + SQLite 存储层。 | 4 | feature_migrate_v071, feature_password, feature_storage, feature_user_model |
| app | Flask app factory + 路由注册 + config 加载 + Jinja templates。 | 4 | feature_app_factory, feature_config, feature_routes, feature_templates |
| auth | 注册 / 登录 / 登出 / session 管理。 | 4 | feature_login, feature_logout, feature_register, feature_session |
| data | (无职责描述) | 0 | (无特性) |
| home | 项目管理系统首页(登录后)。 | 1 | feature_homepage |
| profile | 用户改密码端点模块。 | 1 | feature_change_password |
| projects | 项目看板核心 — 项目 CRUD + 列表 + 整合主页。 | 13 | feature_board, feature_create, feature_delete, feature_list, feature_me, feature_project_members, feature_project_owner, feature_storage, feature_storage_rbac, feature_user_role, feature_user_view, feature_users_list, feature_view |
| rbac | Role-Based Access Control 基础层。 | 4 | feature_create_admin, feature_require_auth, feature_role, feature_storage |
| team | Team module — /team endpoint (human view) + /team/_internal/report (writer). | 2 | feature_team, feature_team_storage |
```

### `--write` 段替换规则

- 锚定 `^## 模块结构\s*$` 或 `^## 模块-特性目录\s*$` 的 h2 heading(RE `SECTION_HEADING_RE`)
- 替换范围: 该 heading 起点 → 下一个 `^## ` heading 起点(不含)
- 其他段(尤其是 `## v0.8.0(当前 milestone,...)`)完全不动
- 若无匹配段: append 到 readme 末尾(异常路径,正常都有)
- 锚定规则**刻意窄**: 只匹配这两个字面 heading,不匹配任何 v0.x.x(当前 milestone,...) 段

### `--backup` 行为

- 必须在 `--write` 之后才有意义;单独 `--backup` 报错
- 写前把**当前** readme 内容(用 UTF-8 写,无 BOM)`cp` 到 `history/project_board_v081_pre_readme/readme.md`
- 备份目录 `BACKUP_DIR = <workspace>/history/project_board_v081_pre_readme/`,`mkdir -p` 自动建

### 注意事项

- **std-lib only**:`argparse` / `ast` / `json` / `re` / `sys` / `pathlib`,无第三方依赖(7/28 教训)
- **UTF-8 stdout**:`configure_stdio()` 启动时 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`,避免 Windows GBK 默认编码下中文乱码(8/7 教训)
- **职责抽取不展开**: 只取第一行 prose,刻意不合并第二段(避免 readme 后续段落污染表格)
- **accounts/projects 的 readme 列出的特性数跟实际 feature_*.py 数量不一致**(如 accounts readme 列 3 但目录有 4 个 feature_*.py): 工具以**实际文件**为准,这是预期行为(避免 readme 滞后导致工具假报)
- **--write 不支持 --module**: --write 永远写完整表格(filter 只影响 stdout 预览,跟 readme 行为解耦)
- 工具本身守自己的规则(行数 < 1000,函数 < 200,docstring 全 `''' '''`,注释块 < 5,每行 < 128 字符)
- cleancode 0 + cleanword 0 验证
