# Telemetry Backend — AW + OpenCode Dashboard Pipeline

## TL;DR

> **Quick Summary**: 在现有 `aw-report` Python 包基础上，扩展为 **三层数据管道**（Collector → Aggregator → Renderer），把当前手写的 dashboard SVG 变成由真实 AW + OpenCode 数据驱动的自动产物，部署形态使用 **GitHub repo + Actions**（无自建服务）。
>
> **Deliverables**:
> - HostSnapshot / Dashboard 两份冻结的 JSON schema 与 dataclass
> - Collector：从 AW HTTP API + OpenCode session 文件生成 HostSnapshot
> - Aggregator：纯函数式跨 host 合并 + 派生指标（并发、节律、delta）
> - Renderer：把当前 SVG 模板参数化，吃 Dashboard JSON 输出 SVG
> - 双仓库 GitHub Actions 联动：private snapshots → public profile
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES — 5 waves
> **Critical Path**: T1 schema → T6 collector → T11 aggregator → T15 renderer → T18 CI 联动

---

## Context

### Original Request
用户已在多轮迭代后定稿了 dashboard SVG 视觉与信息架构，并在前一轮对话中讨论确定了三层后端架构（Collector / Aggregator / Renderer）、HostSnapshot 与 Dashboard 两份契约、4 个 HTTP 端点、隐私脱敏规则、以及部署形态推荐。现在要求生成 Prometheus 工作计划。

### Interview Summary
**Key Discussions**:
- **数据源**：每台 host 的本地 ActivityWatch（macOS 工作机 + Arch Linux 家里机）+ 本地 OpenCode session 文件
- **架构形态**：明确反对单体后端，采用「Collector × N + Aggregator × 1 + Consumer × N」三层
- **部署选择**：在 [Cloudflare Worker / VPS / GitHub repo + Actions] 三选项中，确定使用 **GitHub repo + Actions**（零运维成本，与现有工作流匹配）
- **隐私边界**：原始 window title / URL / 文件路径 / project name / session id 不出本地；公开 dashboard 只展示聚合分类（terminal/browser/other）与公开 host 标签（工作机/家里机）
- **指标定稿**（来自最终 SVG）：
  - 顶部四卡：ACTIVE WORK 30D、TOKENS 7D、WORKSTATIONS、SESSION LOAD 30D
  - 主图：30 天分层柱（终端/浏览器/其他）+ 当日 Token 总量折线 + best day callout
  - 右栏：APPLICATIONS 30D（3 项与主图分层一致）+ TOP MODELS 30D（Top 3）
  - 底部：24H RHYTHM（7d hourly average）
- **会话并发定义**：把每个 OpenCode session 的消息流按 ≤10min 间隔切成 burst，跨 host 跨 session 做 sweep line，得到 avg/peak/return median

### Research Findings
- 现有代码已在 `aw_report/` 下分好 `aw_client.py / collect.py / aggregate.py / render_md.py / render_json.py / models.py / utils.py / config.py / cli.py`，模块边界清晰，符合扩展需要
- AW HTTP API 接口已封装（`AWClient`），bucket 类型映射在 `BUCKET_TYPE_MAP`
- `ReportFacts` dataclass 已支持 per-host + combined 视图，但未覆盖 OpenCode 与跨日聚合
- 当前 SVG 是手写的 `assets/dashboard-demo.svg`，需要参数化为模板
- 项目当前**没有任何测试 / CI / docs 目录**

---

## Work Objectives

### Core Objective
把"看起来很真实但全是假数据"的 dashboard SVG，变成由真实 AW + OpenCode 数据驱动的、每天自动刷新的工程主页面板。

### Concrete Deliverables
- `aw_report/snapshot.py` — 输出 HostSnapshot 的模块
- `aw_report/opencode.py` — OpenCode session 读取与 burst 提取
- `aw_report/categorize.py` — 应用 → 分类映射 + allowlist 过滤
- `aw_report/sanitize.py` — 隐私脱敏过滤层
- `aw_report/aggregate_dashboard.py` — 跨 host 聚合纯函数
- `aw_report/concurrency.py` — sweep-line 并发算法
- `aw_report/render_svg.py` — SVG 模板参数化渲染
- `aw_report/templates/dashboard.svg.tmpl` — SVG 模板（来自当前 demo）
- 新 CLI 命令：`aw-report snapshot day`、`aw-report aggregate`、`aw-report render`
- `tests/` 目录 + pytest fixtures + 单元测试
- `.github/workflows/collect.yml` 与 `.github/workflows/render.yml` 两个 Action

### Definition of Done
- [ ] `aw-report snapshot day --host work-mac` 在本机运行，输出符合 schema 的 HostSnapshot JSON
- [ ] `aw-report aggregate --in snapshots/ --out dashboard.json` 跨多个 HostSnapshot 产出 Dashboard JSON
- [ ] `aw-report render --in dashboard.json --out dashboard.svg` 渲染出与现有 demo 视觉一致的 SVG
- [ ] `pytest` 全部通过，包含 schema 校验、并发算法、跨 host 聚合三类用例
- [ ] GitHub Action 在两台 host 上分别成功推送 snapshot 到 private repo
- [ ] GitHub Action 在 schedule 触发后成功更新 `rqdmap/rqdmap` 的 `assets/dashboard.svg`
- [ ] 公开 SVG 中**不出现**任何 window title / URL / 文件路径 / project name / 真实 hostname / session id

### Must Have
- HostSnapshot schema 包含 `schema_version` 字段，与 Dashboard schema 严格分离
- Collector 输出阶段强制 schema 校验，违反隐私规则的字段必须拒绝写入
- 并发算法采用时间加权平均，不是简单算术平均
- 24H rhythm 是 **近 7 天每小时活跃秒数加权平均**，不是某一天的快照
- SVG 模板与数据完全解耦，模板内不内嵌任何业务数据
- App allowlist 是配置驱动，新增应用无需改代码

### Must NOT Have (Guardrails)
- **不要**引入 web 框架（Django / FastAPI / Flask）— 当前阶段无 HTTP 服务需求
- **不要**新增 SQLite / Postgres / Redis 等持久化 — JSON 文件足够
- **不要**让 collector 直接知道 aggregator 的实现细节 — 只通过 JSON 文件对接
- **不要**在公开仓库存储 HostSnapshot — 必须 private
- **不要**展示 prompt/completion token 拆分 — 已被用户明确否决
- **不要**展示 project name / window title / URL — 隐私红线
- **不要**为了"完整"而新增未在 SVG 中出现的指标 — 当前 SVG 是 source of truth
- **不要**重写已有的 `AWClient` / `collect.py` / `aggregate.py` — 这些是稳定层

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: NO（项目当前无 test 目录）
- **Automated tests**: YES (Tests-after) — 实现 + 测试同任务，但允许先 GREEN
- **Framework**: pytest（Python 3.11+ 原生友好，与项目栈一致）
- **Setup task**: T0 配置 pytest + tests/ 目录骨架

### QA Policy
每个任务必须包含 **Agent-Executed QA Scenarios**：
- **CLI**：用 `Bash` 直接调用 `aw-report ...`，断言 stdout JSON 字段
- **纯函数模块**：用 `Bash` 跑 pytest 单测，断言 PASS 数量与 coverage
- **Schema**：用 `Bash` + `jq` 对输出 JSON 验证字段存在性与类型
- **GitHub Action**：用 `gh workflow run` 触发，`gh run watch` 等待，断言 conclusion=success
- **隐私脱敏**：grep 输出 JSON 是否含禁词，断言 `0 matches`

证据保存至 `.sisyphus/evidence/task-{N}-{slug}.{ext}`。

---

## Execution Strategy

### Parallel Execution Waves

```text
Wave 0 (Foundation - solo):
└── T0:  pytest + tests 骨架 + fixtures 目录                       [quick]

Wave 1 (Schemas + Pure Modules - 6 任务并行):
├── T1:  HostSnapshot dataclass + JSON schema                      [quick]
├── T2:  Dashboard dataclass + JSON schema                         [quick]
├── T3:  App categorize + allowlist 配置加载                       [quick]
├── T4:  sanitize.py 隐私脱敏过滤层                                 [quick]
├── T5:  concurrency.py sweep-line 算法（纯函数）                  [deep]
└── T6:  fixtures：3 份 HostSnapshot 样本 + 1 份目标 Dashboard     [quick]

Wave 2 (Collector - 3 任务并行):
├── T7:  opencode.py session 读取 + burst 提取                     [deep]
├── T8:  snapshot.py 组装 HostSnapshot（依赖 T1, T3, T4, T7）      [deep]
└── T9:  CLI: aw-report snapshot day                               [quick]

Wave 3 (Aggregator - 4 任务并行):
├── T10: 跨 host 合并函数（依赖 T1, T2）                           [unspecified-high]
├── T11: 30d trend + delta vs 前 30d 计算                          [quick]
├── T12: 7d hourly rhythm 加权平均                                  [quick]
└── T13: best_day 选取 + cards 字段填充                            [quick]
   ↓
└── T14: aggregate_dashboard.py 顶层 aggregate() 整合（依赖 T10-T13） [deep]

Wave 4 (Renderer - 3 任务并行):
├── T15: 抽取当前 dashboard-demo.svg 为模板（依赖 T2）             [unspecified-high]
├── T16: render_svg.py 模板渲染引擎                                [deep]
└── T17: CLI: aw-report aggregate / render                          [quick]

Wave 5 (CI/Storage - 2 任务并行):
├── T18: collect.yml — 双 host 上 cron 推 snapshot 到 private repo [unspecified-high]
└── T19: render.yml — 拉 snapshots → aggregate → render → commit  [unspecified-high]

Wave FINAL (并行 4 路 review):
├── F1: 计划合规审计                                                [oracle]
├── F2: 代码质量与隐私红线审查                                      [unspecified-high]
├── F3: 端到端 QA：本机跑通完整链路                                  [unspecified-high]
└── F4: 范围保真度对照                                              [deep]
→ 汇总报告 → 等待用户 okay

Critical Path: T0 → T1 → T8 → T14 → T16 → T19 → F1-F4 → user okay
Parallel Speedup: ~65% faster than sequential
Max Concurrent: 6 (Wave 1)
```

### Dependency Matrix

- **T0**: — → T1-T6, 1
- **T1**: T0 → T8, T10, T15, 1
- **T2**: T0 → T10, T15, 1
- **T3**: T0 → T8, 1
- **T4**: T0 → T8, 1
- **T5**: T0 → T10, 1
- **T6**: T0 → T10-T16, 1
- **T7**: T0 → T8, 1
- **T8**: T1, T3, T4, T7 → T9, T18, 2
- **T9**: T8 → T18, 2
- **T10**: T1, T2, T5, T6 → T14, 3
- **T11**: T2, T6 → T14, 3
- **T12**: T2, T6 → T14, 3
- **T13**: T2, T6 → T14, 3
- **T14**: T10-T13 → T17, 3
- **T15**: T2 → T16, 4
- **T16**: T15 → T17, 4
- **T17**: T14, T16 → T19, 4
- **T18**: T9 → T19, 5
- **T19**: T17, T18 → F1-F4, 5

### Agent Dispatch Summary

- **Wave 0**: T0 → `quick`
- **Wave 1**: T1-T4, T6 → `quick`；T5 → `deep`
- **Wave 2**: T7, T8 → `deep`；T9 → `quick`
- **Wave 3**: T10 → `unspecified-high`；T11-T13 → `quick`；T14 → `deep`
- **Wave 4**: T15 → `unspecified-high`；T16 → `deep`；T17 → `quick`
- **Wave 5**: T18, T19 → `unspecified-high`
- **FINAL**: F1 → `oracle`；F2, F3 → `unspecified-high`；F4 → `deep`

---

## TODOs

- [ ] 0. Pytest infra + tests 骨架

  **What to do**:
  - 在 `pyproject.toml` 增加 `[project.optional-dependencies] dev = ["pytest>=8", "pytest-cov"]`
  - 创建 `tests/` 目录、`tests/__init__.py`、`tests/conftest.py`
  - 创建 `tests/fixtures/` 目录用于存放 JSON 样本
  - 在 `pyproject.toml` 加 `[tool.pytest.ini_options] testpaths = ["tests"]`
  - 写一个 sanity test `tests/test_smoke.py` 验证 `import aw_report; assert aw_report.__version__`

  **Must NOT do**:
  - 不要修改任何 `aw_report/` 现有源码
  - 不要引入除 pytest/pytest-cov 外的测试依赖

  **Recommended Agent Profile**:
  - **Category**: `quick` — 单文件配置 + 目录创建
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO（其他任务都依赖 pytest 已就绪）
  - **Blocks**: T1-T6
  - **Blocked By**: None

  **References**:
  - `pyproject.toml` — 现有 hatchling 配置，扩展 optional-dependencies
  - `aw_report/__init__.py:1` — `__version__` 字段位置

  **Acceptance Criteria**:
  - [ ] `pip install -e ".[dev]"` 成功
  - [ ] `pytest -v` 跑通 smoke test
  - [ ] `tests/fixtures/` 目录存在

  **QA Scenarios**:
  ```text
  Scenario: pytest 配置生效
    Tool: Bash
    Steps:
      1. 运行 `pip install -e ".[dev]"`
      2. 运行 `pytest -v --co` 列出所有测试用例
      3. 验证 `tests/test_smoke.py::test_import` 出现在列表中
    Expected: smoke test 被发现并通过
    Evidence: .sisyphus/evidence/task-0-pytest-setup.txt
  ```

  **Commit**: YES — `chore(test): bootstrap pytest infrastructure`

---

- [ ] 1. HostSnapshot dataclass + JSON schema

  **What to do**:
  - 在 `aw_report/models.py` 追加 `HostMeta`, `OpenCodeBurst`, `OpenCodeSession`, `HostSnapshot` dataclass
  - 字段严格遵循已确定的契约（见下方 Reference）
  - 增加 `schema_version: str = "1.0"` 在 root
  - 实现 `HostSnapshot.to_json() -> str` 与 `HostSnapshot.from_json(s: str) -> HostSnapshot`
  - 实现 `HostSnapshot.validate()` — 强制隐私字段缺失校验

  **Must NOT do**:
  - 不要包含 window title / URL / 文件路径 / project name 字段
  - session_id 字段必须存储为已哈希字符串，不接受原始 ID

  **Recommended Agent Profile**: `quick`

  **Parallelization**: 与 T2-T6 并行

  **References**:
  - 上一轮设计中的 HostSnapshot JSON 样例（用户已批准）
  - `aw_report/models.py` 现有 dataclass 风格

  **Acceptance Criteria**:
  - [ ] `tests/test_host_snapshot_schema.py` 至少 5 个测试通过
  - [ ] `validate()` 对缺失 `host.label` / `host.platform` / `date` 抛错
  - [ ] `to_json` / `from_json` 双向稳定（roundtrip 等价）

  **QA Scenarios**:
  ```text
  Scenario: roundtrip 等价
    Tool: Bash
    Steps:
      1. 构造 HostSnapshot 实例 a
      2. b = HostSnapshot.from_json(a.to_json())
      3. assert a == b
    Evidence: .sisyphus/evidence/task-1-roundtrip.txt
  ```

  **Commit**: YES — `feat(models): add HostSnapshot schema`

---

- [ ] 2. Dashboard dataclass + JSON schema

  **What to do**:
  - 在 `aw_report/models.py` 追加 `Cards`, `WorkstationEntry`, `SessionLoad`, `TimelineEntry`, `BestDay`, `ApplicationEntry`, `ModelEntry`, `Dashboard` dataclass
  - root 含 `schema_version: str = "1.0"` 与 `range`, `header`, `cards`, `timeline_30d`, `best_day`, `applications_30d`, `models_30d`, `rhythm_7d`
  - 实现 `Dashboard.to_json()` / `from_json()` / `validate()`

  **Must NOT do**:
  - 不要包含任何 host_id / session_id / 真实 hostname

  **Recommended Agent Profile**: `quick`

  **Parallelization**: 与 T1, T3-T6 并行

  **References**:
  - 上一轮设计的 Dashboard JSON 样例
  - 当前 `assets/dashboard-demo.svg` — 字段必须能 1:1 喂渲染

  **Acceptance Criteria**:
  - [ ] schema 字段与 SVG 对应表 100% 覆盖
  - [ ] `validate()` 拒绝出现 host_id / session_id 字段

  **QA Scenarios**:
  ```text
  Scenario: 字段覆盖 SVG
    Tool: Bash
    Steps:
      1. 加载 fixtures/sample_dashboard.json
      2. 对照 docs/svg-data-binding.md 中的字段表（在 T15 中创建）
      3. 当前用 grep 检查 cards/timeline_30d/applications_30d/models_30d/rhythm_7d 都存在
    Evidence: .sisyphus/evidence/task-2-fields.txt
  ```

  **Commit**: YES — `feat(models): add Dashboard schema`

---

- [ ] 3. App categorize + allowlist 配置加载

  **What to do**:
  - 创建 `aw_report/categorize.py`
  - 新增 `aw-report.toml` 配置段：
    ```toml
    [categorize.terminal]
    allow = ["Alacritty", "iTerm2", "kitty", "Neovim", "Code", "WezTerm", "Terminal"]
    [categorize.browser]
    allow = ["Google Chrome", "Chromium", "Firefox", "Safari", "Arc"]
    ```
  - 函数 `categorize(app_name: str, config: Config) -> Literal["terminal", "browser", "other"]`
  - 不在 allowlist 的应用：归为 `other`，且**不暴露 app 名**

  **Must NOT do**:
  - 不要硬编码 allowlist 在 .py 文件
  - 不要把 `other` 分类下的具体 app 名传出函数

  **Recommended Agent Profile**: `quick`

  **Parallelization**: 与 T1-T2, T4-T6 并行

  **References**:
  - `aw_report/config.py` — Config dataclass 扩展
  - `aw-report.toml` — 现有 toml 结构

  **Acceptance Criteria**:
  - [ ] 单测覆盖 4 类：terminal allowlist hit / browser allowlist hit / other / 未配置时默认行为
  - [ ] Config 加载向后兼容（旧配置无 categorize 段不报错）

  **QA Scenarios**:
  ```text
  Scenario: allowlist 命中与降级
    Tool: Bash
    Steps:
      1. pytest tests/test_categorize.py
    Expected: 至少 6 个测试 PASS
    Evidence: .sisyphus/evidence/task-3-categorize.txt
  ```

  **Commit**: YES — `feat(categorize): app->category mapping with allowlist`

---

- [ ] 4. sanitize.py 隐私脱敏过滤层

  **What to do**:
  - 创建 `aw_report/sanitize.py`
  - `sanitize_snapshot(raw: dict) -> dict` — 移除/拒绝以下字段：window title、url、file path、project name、真实 hostname
  - `hash_session_id(raw_id: str) -> str` — SHA256 截断 16 字符
  - 提供 `FORBIDDEN_KEYS` 常量列表用于校验
  - 任何匹配到禁词的字段 → 抛出 `PrivacyViolation` 异常

  **Must NOT do**:
  - 不要把禁词列表写到日志或异常消息中以免反向泄露
  - 不要默认通过（fail-open）— 必须 fail-closed

  **Recommended Agent Profile**: `quick`

  **Parallelization**: 与 T1-T3, T5-T6 并行

  **References**:
  - 上一轮"隐私 / 脱敏的强制规则"表格

  **Acceptance Criteria**:
  - [ ] 输入含 `window_title` 字段 → 抛 `PrivacyViolation`
  - [ ] 输入含 `url` / `file_path` / `project_name` / `hostname` → 抛 `PrivacyViolation`
  - [ ] `hash_session_id("ses_abc")` 长度 == 16，确定性

  **QA Scenarios**:
  ```text
  Scenario: 隐私字段拒绝
    Tool: Bash
    Steps:
      1. pytest tests/test_sanitize.py -v
    Expected: 至少 8 个测试 PASS，包含 5 个 PrivacyViolation 用例
    Evidence: .sisyphus/evidence/task-4-sanitize.txt
  ```

  **Commit**: YES — `feat(sanitize): privacy filter with fail-closed semantics`

---

- [ ] 5. concurrency.py sweep-line 并发算法

  **What to do**:
  - 创建 `aw_report/concurrency.py`
  - 函数：`compute_concurrency(bursts: list[Burst]) -> ConcurrencyMetrics`
  - 返回字段：`avg_concurrent`, `peak_concurrent`, `return_median_seconds`, `daily_avg_concurrent_7d: list[float]`
  - sweep line 实现：边界事件 (timestamp, +1/-1, session_id)，按时间排序后线性扫描
  - 时间加权平均：`weighted_sum / union_seconds`
  - return median：每次 session 进入"等待用户"状态到下次该 session 出现 user message 的时间差，取中位数
  - 只计入 `c(t) >= 1` 的时间片到 union，否则纯空隙

  **Must NOT do**:
  - 不要用算术平均（会被低活跃日稀释）
  - 不要把 burst 边界放到本函数外部计算 — burst 是输入，本函数只做聚合

  **Recommended Agent Profile**: `deep` — 算法正确性敏感

  **Parallelization**: 与 T1-T4, T6 并行

  **References**:
  - 上一轮设计中的 `compute_concurrency` Python 草稿
  - 上一轮关于 Active/Pending/Parked 三态的定义

  **Acceptance Criteria**:
  - [ ] 单元测试至少 8 个，覆盖：单 burst、多重叠、跨日、空输入、return median 计算
  - [ ] 给定 fixture：3 session × 7 天 burst 数据 → 输出 `peak == 4, avg in [1.6, 1.8]`
  - [ ] 算术平均与时间加权平均的差异在文档中说明

  **QA Scenarios**:
  ```text
  Scenario: sweep line 正确性
    Tool: Bash
    Steps:
      1. pytest tests/test_concurrency.py -v
    Expected: 全部 PASS
    Evidence: .sisyphus/evidence/task-5-concurrency.txt
  ```

  **Commit**: YES — `feat(concurrency): sweep-line session load algorithm`

---

- [ ] 6. Test fixtures：3 份 HostSnapshot + 1 份目标 Dashboard

  **What to do**:
  - 创建 `tests/fixtures/snapshot-work-mac-2026-04-21.json`
  - 创建 `tests/fixtures/snapshot-home-arch-2026-04-21.json`
  - 创建 `tests/fixtures/snapshot-work-mac-2026-04-20.json`（用于跨日聚合）
  - 创建 `tests/fixtures/dashboard-expected.json` — 三份 snapshot 经过 aggregate 后的预期产物
  - 数据用 mock，但**结构与字段类型必须真实**

  **Must NOT do**:
  - 不要包含真实 OpenCode session id
  - 不要包含真实 hostname

  **Recommended Agent Profile**: `quick`

  **Parallelization**: 与 T1-T5 并行

  **References**:
  - T1, T2 的 schema 定义
  - 现有 `assets/dashboard-demo.svg` 中的所有数字（用作 dashboard-expected.json 的目标值）

  **Acceptance Criteria**:
  - [ ] 4 个 JSON 文件存在且通过对应 schema validate
  - [ ] dashboard-expected.json 中的数字与当前 SVG 一致

  **QA Scenarios**:
  ```text
  Scenario: fixtures 通过 schema 校验
    Tool: Bash
    Steps:
      1. pytest tests/test_fixtures_schema.py
    Expected: PASS
    Evidence: .sisyphus/evidence/task-6-fixtures.txt
  ```

  **Commit**: YES — `test(fixtures): add snapshot+dashboard fixtures`

---

- [ ] 7. opencode.py session 读取 + burst 提取

  **What to do**:
  - 创建 `aw_report/opencode.py`
  - 函数 `read_sessions(opencode_dir: Path, date: date) -> list[OpenCodeSession]`
    - 读取 `~/.local/share/opencode/sessions/*.jsonl` 或类似路径（先 hardcode，后续可配）
    - 过滤目标日期内有消息的 session
  - 函数 `extract_bursts(messages: list[Message], gap_minutes: int = 10) -> list[Burst]`
    - 相邻消息间隔 ≤10 分钟为同一 burst
    - 输出每个 burst 的 (start, end)
  - 函数 `extract_token_usage(messages) -> dict` — 按 model 聚合 token

  **Must NOT do**:
  - 不要读取 message content / file 操作明细
  - 不要把 session_id 原文带出 — 必须用 sanitize.hash_session_id

  **Recommended Agent Profile**: `deep` — OpenCode 文件格式需要探索

  **Parallelization**: 与 T8 之前的所有任务并行

  **References**:
  - `~/.local/share/opencode/` — 实际 OpenCode 数据目录
  - `aw_report/sanitize.py:hash_session_id`（T4）

  **Acceptance Criteria**:
  - [ ] 给定 fixture session 文件 → 正确切出 burst
  - [ ] gap=10min 时，相距 9min 的两条消息合并；相距 12min 拆开
  - [ ] 输出不含原始 session_id 与 message content

  **QA Scenarios**:
  ```text
  Scenario: burst 切割
    Tool: Bash
    Steps:
      1. pytest tests/test_opencode.py -v
    Expected: PASS
    Evidence: .sisyphus/evidence/task-7-opencode.txt
  ```

  **Commit**: YES — `feat(opencode): session reader + burst extractor`

---

- [ ] 8. snapshot.py 组装 HostSnapshot

  **What to do**:
  - 创建 `aw_report/snapshot.py`
  - 函数 `build_host_snapshot(client: AWClient, opencode_dir: Path, date: date, host_meta: HostMeta, config: Config) -> HostSnapshot`
  - 步骤：
    1. AW 收集：调用现有 `collect_active_windows` / `collect_input` 等
    2. 应用分类：用 `categorize(app, config)` 计算 `by_category` 与 `applications` 列表
    3. OpenCode 收集：调用 `read_sessions` + `extract_bursts` + `extract_token_usage`
    4. 24 元素 rhythm：当日按小时统计活跃秒数
    5. 调用 `sanitize_snapshot` 校验最终输出

  **Must NOT do**:
  - 不要重写 AW 数据收集逻辑 — 复用 `aw_report/collect.py`
  - 不要在本模块内做跨日聚合 — 那是 aggregator 的职责

  **Recommended Agent Profile**: `deep`

  **Parallelization**: 依赖 T1, T3, T4, T7 完成

  **References**:
  - `aw_report/collect.py` — 复用现有 collector
  - `aw_report/aw_client.py` — 复用 AWClient

  **Acceptance Criteria**:
  - [ ] 给定 mock AW response + mock opencode dir → 输出符合 HostSnapshot schema 的 dict
  - [ ] 输出能被 `sanitize_snapshot` 验证通过

  **QA Scenarios**:
  ```text
  Scenario: 端到端 snapshot 构建
    Tool: Bash
    Steps:
      1. pytest tests/test_snapshot.py -v
    Expected: PASS
    Evidence: .sisyphus/evidence/task-8-snapshot.txt
  ```

  **Commit**: YES — `feat(snapshot): assemble HostSnapshot from AW + OpenCode`

---

- [ ] 9. CLI: aw-report snapshot day

  **What to do**:
  - 在 `aw_report/cli.py` 新增 `snapshot` group + `day` 子命令
  - 参数：`--host <id>`（必填）、`--date <YYYY-MM-DD>`（默认今天）、`--out <path>`（默认 stdout）
  - 从 config 读取 `[host_meta.<id>]` 段
  - 调用 `build_host_snapshot` 并输出 JSON

  **Must NOT do**:
  - 不要让 CLI 默认覆盖文件 — 须显式 `--out`

  **Recommended Agent Profile**: `quick`

  **Parallelization**: 依赖 T8

  **References**:
  - `aw_report/cli.py` — 现有 Click group 结构

  **Acceptance Criteria**:
  - [ ] `aw-report snapshot day --host work-mac` 在测试环境跑通
  - [ ] 输出 JSON 通过 HostSnapshot schema 校验

  **QA Scenarios**:
  ```text
  Scenario: CLI 输出 schema 合规
    Tool: Bash
    Steps:
      1. aw-report snapshot day --host work-mac --date 2026-04-21 --out /tmp/snap.json
      2. python -c "from aw_report.models import HostSnapshot; import json; HostSnapshot.from_json(open('/tmp/snap.json').read()).validate()"
    Expected: 退出码 0
    Evidence: .sisyphus/evidence/task-9-cli-snapshot.txt
  ```

  **Commit**: YES — `feat(cli): aw-report snapshot day`

---

- [ ] 10. 跨 host 合并函数

  **What to do**:
  - 在 `aw_report/aggregate_dashboard.py` 实现 `merge_hosts(snapshots: list[HostSnapshot]) -> dict`
  - 按 host 累加 active_seconds 与 by_category
  - 应用列表跨 host 合并（按 name + category 聚合）
  - rhythm 数组按 host 累加（24 元素相加）
  - 收集所有 burst 用于后续并发计算

  **Must NOT do**:
  - 不要在合并阶段做时间窗口截断 — 那是上层职责

  **Recommended Agent Profile**: `unspecified-high`

  **Parallelization**: 与 T11-T13 并行

  **References**:
  - `aw_report/aggregate.py:_merge_host_sections` — 现有跨 host 合并参考

  **Acceptance Criteria**:
  - [ ] 给定 2 host 的同日 snapshot → 合并后 active_seconds 等于两者之和
  - [ ] applications 列表去重正确（同 name 累加）

  **QA Scenarios**:
  ```text
  Scenario: 跨 host 合并
    Tool: Bash
    Steps:
      1. pytest tests/test_merge_hosts.py -v
    Expected: PASS
    Evidence: .sisyphus/evidence/task-10-merge.txt
  ```

  **Commit**: YES — `feat(aggregate): cross-host merge`

---

- [ ] 11. 30d trend + delta vs 前 30d

  **What to do**:
  - 函数 `build_timeline_30d(snapshots_by_date: dict[date, list]) -> list[TimelineEntry]`
  - 函数 `compute_delta(curr_period_seconds, prev_period_seconds) -> int` — 返回百分比
  - 缺日填 0，不跳过

  **Must NOT do**:
  - 不要插值 — 缺日就是 0

  **Recommended Agent Profile**: `quick`

  **Parallelization**: 与 T10, T12, T13 并行

  **References**: T6 fixtures

  **Acceptance Criteria**:
  - [ ] 30 个 entries 完整无缺
  - [ ] delta_pct 计算正确（rounding 与符号）

  **QA Scenarios**:
  ```text
  Scenario: timeline 完整与 delta 正确
    Tool: Bash
    Steps:
      1. pytest tests/test_timeline.py -v
    Expected: PASS
    Evidence: .sisyphus/evidence/task-11-timeline.txt
  ```

  **Commit**: YES — `feat(aggregate): 30d timeline + delta`

---

- [ ] 12. 7d hourly rhythm 加权平均

  **What to do**:
  - 函数 `compute_rhythm_7d(snapshots_last_7_days: list[HostSnapshot]) -> list[int]`
  - 把每日 24 元素 rhythm 数组按位累加，然后 `/ 7`（或 `/ 实际有数据天数`）
  - 单位仍为秒

  **Must NOT do**:
  - 不要按峰值标准化 — 输出的是平均秒数

  **Recommended Agent Profile**: `quick`

  **Parallelization**: 与 T10, T11, T13 并行

  **References**: T6 fixtures

  **Acceptance Criteria**:
  - [ ] 输出长度 == 24
  - [ ] 给 fixture 的预期值匹配

  **QA Scenarios**:
  ```text
  Scenario: rhythm 加权平均正确
    Tool: Bash
    Steps:
      1. pytest tests/test_rhythm.py -v
    Expected: PASS
    Evidence: .sisyphus/evidence/task-12-rhythm.txt
  ```

  **Commit**: YES — `feat(aggregate): 7d hourly rhythm averaging`

---

- [ ] 13. best_day 选取 + cards 字段填充

  **What to do**:
  - 函数 `select_best_day(timeline: list[TimelineEntry]) -> BestDay` — 按 active 总时长选
  - 函数 `build_cards(...) -> Cards` — 装填 4 个卡片所需的所有数字
  - 包括 workstations 列表、session_load 字段（依赖 T5 的 ConcurrencyMetrics）

  **Recommended Agent Profile**: `quick`

  **Parallelization**: 与 T10-T12 并行

  **References**: T2 schema, T5 concurrency

  **Acceptance Criteria**:
  - [ ] `select_best_day` 选出 fixture 中预期的日期与时长
  - [ ] cards.session_load 包含 4 个字段：avg_concurrent, peak_concurrent, return_median_seconds, trend_7d

  **QA Scenarios**:
  ```text
  Scenario: best day 选取与 cards 字段
    Tool: Bash
    Steps:
      1. pytest tests/test_best_day.py tests/test_cards.py -v
    Expected: PASS
    Evidence: .sisyphus/evidence/task-13-cards.txt
  ```

  **Commit**: YES — `feat(aggregate): best_day + cards builders`

---

- [ ] 14. aggregate_dashboard.py 顶层 aggregate() 整合

  **What to do**:
  - 在 `aw_report/aggregate_dashboard.py` 提供顶层入口：
    `aggregate(snapshots: list[HostSnapshot], today: date) -> Dashboard`
  - 内部按顺序：
    1. 按日期分组
    2. 调用 `merge_hosts` 得到每日合并视图
    3. 调用 `build_timeline_30d` / `compute_rhythm_7d` / `compute_concurrency` / `select_best_day`
    4. 调用 `build_cards` 装填卡片
    5. 装配 `applications_30d`（30 天合并）与 `models_30d`（30 天合并）
    6. 输出 `Dashboard` 实例

  **Recommended Agent Profile**: `deep`

  **Parallelization**: 依赖 T10-T13 完成

  **References**: 上述所有子模块

  **Acceptance Criteria**:
  - [ ] 输入 fixture 3 份 snapshot → 输出与 `dashboard-expected.json` 完全一致（除 generated_at）

  **QA Scenarios**:
  ```text
  Scenario: 端到端 aggregate 与 fixture 匹配
    Tool: Bash
    Steps:
      1. pytest tests/test_aggregate_e2e.py -v
    Expected: 输出与 dashboard-expected.json 一致（diff 仅 generated_at）
    Evidence: .sisyphus/evidence/task-14-aggregate-e2e.txt
  ```

  **Commit**: YES — `feat(aggregate): top-level aggregate() integration`

---

- [ ] 15. 抽取 dashboard-demo.svg 为模板

  **What to do**:
  - 复制 `assets/dashboard-demo.svg` → `aw_report/templates/dashboard.svg.tmpl`
  - 把所有数字、文本、bar 高度、polyline 点位、文本标签替换为占位符
  - 推荐使用 `string.Template` 或 Jinja2（如选 Jinja2 则加入依赖）
  - **仅替换数据，不动结构、布局、配色、字体**
  - 输出一份 `docs/svg-data-binding.md` 列出每个占位符与 Dashboard JSON 字段的映射

  **Must NOT do**:
  - 不要为了美化而调整 SVG 结构 — 当前 SVG 已被用户定稿
  - 不要引入 cairosvg / lxml 等重量级库

  **Recommended Agent Profile**: `unspecified-high`

  **Parallelization**: 与 T16, T17 并行（T16 依赖本任务的占位符约定）

  **References**:
  - `assets/dashboard-demo.svg` — source of truth
  - T2 Dashboard schema

  **Acceptance Criteria**:
  - [ ] 模板渲染当前 fixture 数据后，diff 结果与原 SVG 仅在数字/文本上不同
  - [ ] 文档列出 100% 字段映射

  **QA Scenarios**:
  ```text
  Scenario: 模板还原原图
    Tool: Bash
    Steps:
      1. python -c "...用 fixtures/dashboard-expected.json 渲染模板..."
      2. diff rendered.svg assets/dashboard-demo.svg
    Expected: diff 仅在数据节点
    Evidence: .sisyphus/evidence/task-15-template.txt
  ```

  **Commit**: YES — `feat(templates): parameterized dashboard SVG template`

---

- [ ] 16. render_svg.py 模板渲染引擎

  **What to do**:
  - 创建 `aw_report/render_svg.py`
  - 函数 `render_dashboard(dashboard: Dashboard) -> str`
  - 加载模板 → 计算所有派生几何（bar 高度像素、polyline 点位、rhythm 单元格颜色）→ 替换占位符
  - 对超界数据自动 clamp（防止 token 异常值飞出图）

  **Must NOT do**:
  - 不要把布局参数（坐标、宽度）硬编码 — 抽到模块顶部常量

  **Recommended Agent Profile**: `deep`

  **Parallelization**: 依赖 T15

  **References**: T15 模板与字段映射文档

  **Acceptance Criteria**:
  - [ ] 给定 fixture Dashboard → 输出 SVG 文件能被浏览器打开（XML 合法）
  - [ ] clamp 测试：异常 token 值 999M → polyline 仍在 chart 区域内

  **QA Scenarios**:
  ```text
  Scenario: 渲染输出合法 SVG
    Tool: Bash
    Steps:
      1. pytest tests/test_render_svg.py -v
      2. xmllint --noout /tmp/rendered.svg
    Expected: 退出码 0
    Evidence: .sisyphus/evidence/task-16-render.txt
  ```

  **Commit**: YES — `feat(render): SVG template rendering engine`

---

- [ ] 17. CLI: aw-report aggregate / render

  **What to do**:
  - 新增 `aw-report aggregate --in <snapshots-dir> --out <dashboard.json>` — 调用 T14
  - 新增 `aw-report render --in <dashboard.json> --out <dashboard.svg>` — 调用 T16

  **Recommended Agent Profile**: `quick`

  **Parallelization**: 依赖 T14, T16

  **References**: 现有 CLI 结构

  **Acceptance Criteria**:
  - [ ] 两条命令端到端跑通：snapshots → dashboard.json → dashboard.svg

  **QA Scenarios**:
  ```text
  Scenario: 端到端 CLI 链路
    Tool: Bash
    Steps:
      1. aw-report aggregate --in tests/fixtures --out /tmp/d.json
      2. aw-report render --in /tmp/d.json --out /tmp/d.svg
      3. xmllint --noout /tmp/d.svg
    Expected: 全部退出码 0
    Evidence: .sisyphus/evidence/task-17-cli-chain.txt
  ```

  **Commit**: YES — `feat(cli): aggregate + render commands`

---

- [ ] 18. GitHub Action: collect.yml（双 host）

  **What to do**:
  - 在 `.github/workflows/collect.yml` 创建一个 **可手动触发 + cron** 的 workflow
  - 注：实际生产 collector 需在 self-hosted runner（即用户本机）上运行，因为 AW 在 127.0.0.1:5600
  - workflow 步骤：
    1. checkout `aw-report` repo
    2. `pip install -e .`
    3. `aw-report snapshot day --host ${HOST_LABEL} --out snapshot.json`
    4. push 到 private snapshots repo（用 deploy key）
  - 生成两份 workflow（或一份用 matrix）：work-mac、home-arch
  - 文档化 self-hosted runner 配置步骤到 `docs/deployment.md`

  **Must NOT do**:
  - 不要让 workflow 在 GitHub-hosted runner 上跑 collector — 拿不到本机 AW
  - 不要把 deploy key 明文写入 workflow

  **Recommended Agent Profile**: `unspecified-high`

  **Parallelization**: 与 T19 并行

  **References**:
  - GitHub self-hosted runner 文档
  - 用户的 private snapshots repo（需用户提前创建）

  **Acceptance Criteria**:
  - [ ] workflow 文件 lint 通过（`actionlint`）
  - [ ] `docs/deployment.md` 包含完整 self-hosted runner 配置说明

  **QA Scenarios**:
  ```text
  Scenario: workflow lint 通过
    Tool: Bash
    Steps:
      1. actionlint .github/workflows/collect.yml
    Expected: 退出码 0
    Evidence: .sisyphus/evidence/task-18-actionlint.txt
  ```

  **Commit**: YES — `ci(collect): per-host snapshot workflow`

---

- [ ] 19. GitHub Action: render.yml

  **What to do**:
  - 在 `.github/workflows/render.yml` 创建 schedule + workflow_dispatch 触发的 workflow
  - 在 GitHub-hosted runner 上跑（不需要本机 AW）
  - 步骤：
    1. checkout 三个 repo：`aw-report`（current）、`snapshots-private`（私有）、`rqdmap`（profile public）
    2. `pip install -e ./aw-report`
    3. `aw-report aggregate --in ./snapshots-private --out dashboard.json`
    4. `aw-report render --in dashboard.json --out dashboard.svg`
    5. commit + push 到 `rqdmap/rqdmap` 的 `assets/dashboard.svg`
  - 包含 marker 自动更新 README 摘要段（参考 Lincest 的 `<!--START_SECTION:waka-->`）

  **Must NOT do**:
  - 不要把 snapshots-private 的内容 commit 到任何 public 仓库
  - 不要在 workflow 中暴露 token 到日志

  **Recommended Agent Profile**: `unspecified-high`

  **Parallelization**: 与 T18 并行

  **References**:
  - 上一轮中关于 Lincest workflow 模式的分析
  - GitHub Actions 推送到外部 repo 的 deploy key 模式

  **Acceptance Criteria**:
  - [ ] workflow 文件 lint 通过
  - [ ] `dry-run` 模式下能本地模拟跑通

  **QA Scenarios**:
  ```text
  Scenario: workflow 本地 dry-run
    Tool: Bash
    Steps:
      1. act -W .github/workflows/render.yml --dryrun
    Expected: 退出码 0
    Evidence: .sisyphus/evidence/task-19-render-dryrun.txt
  ```

  **Commit**: YES — `ci(render): aggregate + render + publish workflow`

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** — `oracle`
  通读本计划，对每个 "Must Have" 验证实现存在；对每个 "Must NOT Have" 在最终代码中 grep 禁止模式（web 框架 import、数据库 import、project name 出现在公开输出等）。
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT`

- [ ] F2. **Code Quality + Privacy Review** — `unspecified-high`
  跑 `pytest -v`、`mypy aw_report/`（如有）、grep `as any` / 空 catch / `print(`。重点审查 `sanitize.py` 是否被绕过：所有写入 HostSnapshot 输出的代码路径都必须经过 `sanitize_snapshot`。
  Output: `Build [PASS/FAIL] | Tests [N/N] | Privacy paths [PASS/FAIL] | VERDICT`

- [ ] F3. **End-to-End Real QA** — `unspecified-high`
  从干净状态出发执行：本机运行 `aw-report snapshot day` → 把两份真实 snapshot 喂给 `aggregate` → 渲染 → 浏览器打开 SVG → 比对当前 demo SVG 视觉一致性。检查 SVG 中是否有任何禁词（grep）。
  Output: `End-to-End [PASS/FAIL] | Visual diff [清单] | Privacy grep [PASS/FAIL] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  对每个 task 的 "What to do" 与实际 diff 做 1:1 对照。重点检查：是否新增了未在 SVG 中出现的指标（违反 "Must NOT" 之"为完整而新增"）；是否擅自调整了 SVG 视觉结构。
  Output: `Tasks [N/N] | Scope creep [CLEAN/N issues] | Visual drift [CLEAN/N] | VERDICT`

---

## Commit Strategy

- 每个 task 一个 commit，使用 `<type>(<scope>): <desc>` 格式
- types: `feat / fix / chore / test / ci / docs / refactor`
- 每个 commit 前必须本地跑过对应 task 的 QA scenarios

---

## Success Criteria

### Verification Commands
```bash
# 端到端
aw-report snapshot day --host work-mac --out /tmp/snap-mac.json
aw-report snapshot day --host home-arch --out /tmp/snap-arch.json
aw-report aggregate --in /tmp/ --out /tmp/dashboard.json
aw-report render --in /tmp/dashboard.json --out /tmp/dashboard.svg
xmllint --noout /tmp/dashboard.svg && echo OK

# 隐私
grep -E "window_title|file_path|project_name|hostname" /tmp/dashboard.json
# Expected: 0 matches

# 测试
pytest -v --cov=aw_report
# Expected: 至少 80% coverage，全 PASS
```

### Final Checklist
- [ ] 所有 "Must Have" 在公开 SVG 与 Dashboard JSON 中可见
- [ ] 所有 "Must NOT Have" grep 不到
- [ ] 端到端链路无人工介入跑通
- [ ] 双 host 推送 → 自动渲染 → 公开主页更新闭环成立
- [ ] 现有 `aw-report` 旧命令（`report`、`facts`）依然可用，无回归
