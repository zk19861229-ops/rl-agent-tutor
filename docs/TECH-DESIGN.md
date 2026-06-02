# RL Agent Tutor — 技术设计文档（Technical Design）

| 字段 | 值 |
|------|-----|
| 文档版本 | v0.3.0 |
| 对应代码版本 | commit `82e3bf1` |
| 最后更新 | 2026-05-25 |
| 关联文档 | [PRD.md](./PRD.md) · [architecture.md](./architecture.md) |

---

## 目录

1. [设计目标与原则](#1-设计目标与原则)
2. [模块拆分](#2-模块拆分)
3. [数据模型](#3-数据模型)
4. [关键流程](#4-关键流程)
5. [接口契约（CLI · HTTP · Agent）](#5-接口契约cli--http--agent)
6. [RAG 子系统设计](#6-rag-子系统设计)
7. [LLM 抽象与容错](#7-llm-抽象与容错)
8. [存储与配置](#8-存储与配置)
9. [并发与一致性](#9-并发与一致性)
10. [部署方案](#10-部署方案)
11. [安全与隐私](#11-安全与隐私)
12. [可观测性](#12-可观测性)
13. [设计权衡](#13-设计权衡)
14. [已知限制与遗留问题](#14-已知限制与遗留问题)

---

## 1. 设计目标与原则

| 原则 | 体现 |
|------|------|
| **数据本地化** | JSON / JSONL / Markdown 全落在 `workspace/` 下，无远程服务 |
| **状态机驱动** | Plan + Node 双层状态机，避免 ad-hoc if-else |
| **多 Agent 单一职责** | 每个 `*.py` 一个 Agent，自带 system prompt |
| **可降级而非阻断** | 任何外部源（arxiv/git/blog/yt/PDF）失败都不应阻断主流程 |
| **可审计** | `trajectory.jsonl` 全留痕 |
| **可移植** | 纯文本、人类可读，可 git，可手改 |

**Anti-goals（明确不做）**：
- 不做"通用 Agent 框架"——只为这一个学习场景设计
- 不抽象数据库——文件就够了
- 不引入消息队列——单进程内的同步调用足够

---

## 2. 模块拆分

```
src/rl_agent_tutor/
├── 入口层
│   ├── cli.py              # typer CLI（28 个命令）
│   ├── server.py           # FastAPI Web UI（50+ 路由 + 内嵌 HTML）
│   └── scheduler.py        # APScheduler daemon
│
├── Agent 层（每个一个职责）
│   ├── orchestrator.py     # 状态机
│   ├── planner.py          # 出计划
│   ├── librarian.py        # 抓资源
│   ├── tutor.py            # 答疑（RAG 注入）
│   ├── examiner.py         # 出题 + 评分（RAG 注入）
│   ├── practice.py         # 行业实践
│   ├── courseware.py       # 资源 → 课件
│   ├── archivist.py        # 蒸馏成 KB（RAG 注入）
│   └── reviewer.py         # 周/阶段复盘
│
├── 核心服务层
│   ├── llm.py              # Anthropic / OpenRouter 封装 + 重试 + JSON 救援
│   ├── rag.py              # BM25 + LLM rerank
│   ├── indexer.py          # PDF → chunk → BM25
│   ├── fetchers.py         # 博客 / YouTube 字幕抓取
│   ├── sources/            # 可配置资源源 registry
│   ├── services/evidence.py # 资源证据链
│   ├── services/workflow.py # 今日任务推荐动作
│   ├── services/dashboard.py # 能力看板指标
│   ├── courseware_schema.py # 结构化课件模型
│   ├── store.py            # JSON/JSONL 持久化
│   ├── workspaces.py       # 多工作区管理
│   ├── config.py           # 环境变量 + 工作区解析
│   └── models.py           # Pydantic 数据模型
│
└── deploy/
    ├── install-native.sh
    ├── Dockerfile
    ├── docker-compose.yml
    ├── com.rlagent.{web,daemon}.plist  # macOS launchd
    └── rl-agent-{web,daemon}.service   # Linux systemd user
```

Web UI 源码以 `src/rl_agent_tutor/web/index.html`、`style.css`、`app.js`
为准。`src/rl_agent_tutor/static/index.html` 是通过
`python scripts/build_static.py` 生成的单文件兼容产物,由
`tests/unit/test_static_build.py` 防止漂移。

**模块依赖原则**：Agent 层只能依赖核心服务层；核心服务层之间允许相互依赖；入口层调用 Agent 层。

---

## 3. 数据模型

### 3.1 Pydantic 模型（`models.py`）

```python
class LearningNode:
    id: str                          # "0.1", "2.3"
    name: str
    description: str
    objectives: list[str]            # 必须有可验证产出
    estimated_hours: tuple[float, float]
    status: "pending" | "in_progress" | "self_testing" | "completed"
    notes: str
    completed_at: str | None

class Stage:
    id: int
    name: str
    description: str
    nodes: list[LearningNode]

class LearningPlan:
    goal: str
    starting_level: str
    stages: list[Stage]
    state: "planning" | "studying" | "self_testing" | "reviewing" | "advancing" | "done"
    current_node_id: str | None
    created_at: str
    updated_at: str
    # 工具方法：all_nodes / find_node / stage_of / next_pending_node

class Resource:
    node_id: str
    kind: "paper" | "code" | "video" | "blog" | "note"
    title: str
    url: str | None
    local_path: str | None
    fetched_at: str
    summary: str
    source_id: str
    priority: "core" | "normal" | "supplemental"
    status: "recommended" | "fetched" | "read" | "cited" | "tested" | "archived" | "rejected"
    used_by: list[str]

class TrajectoryEntry:
    ts: str
    node_id: str | None
    kind: "plan" | "study" | "ask" | "answer" | "fetch" | "test" | "advance" | "review"
    content: str
    meta: dict

class ExerciseQuestion:
    qid: str
    type: "concept" | "derivation" | "code-debug" | "discussion"
    question: str
    expected_points: list[str]

class ExerciseAttempt:
    qid: str
    answer: str
    score: float        # 0..1
    feedback: str
    attempted_at: str

class ExerciseSession:
    node_id: str
    questions: list[ExerciseQuestion]
    attempts: list[ExerciseAttempt]
    started_at: str
    finished_at: str | None
    overall_score: float | None

class Courseware:
    node_id: str
    title: str
    learning_objectives: list[str]
    sections: list[CoursewareSection]
    key_takeaways: list[str]
    references: list[CoursewareReference]

class ContentBlock:
    type: "paragraph" | "callout" | "formula" | "code" | "table" | "diagram" | "image" | "video" | "quiz" | "reference"
    title: str
    content: dict
```

### 3.2 文件布局

```
workspace/
├── progress/
│   ├── plan.json              # 单文件，整个 LearningPlan 序列化
│   ├── trajectory.jsonl       # 追加写
│   ├── resources.jsonl        # 追加写
│   └── exercises.jsonl        # 追加写
└── library/
    ├── papers/                # arxiv PDF
    ├── code/                  # git clone --depth 1
    ├── notes/
    │   ├── blogs/             # 抓回来的博客 .md
    │   ├── transcripts/       # YouTube 字幕 .md
    │   ├── courseware/        # 课件 .md
    │   ├── reviews/           # 周/阶段复盘 .md
    │   ├── nudges/            # 闲置提醒 .md
    │   ├── INDEX.md           # KB 顶层索引
    │   └── <node_id>_<slug>.md  # 每节点的 KB 条目
    └── index/
        ├── chunks.jsonl       # PDF 切块结果
        └── bm25.pkl           # BM25 索引（pickle）
```

---

## 4. 关键流程

### 4.1 规划流程

```
用户输入: goal + level
  ↓
Planner.make_plan()
  ↓ chat_json (system prompt: 4-6 stages, verifiable deliverables)
LLM 返回: structured JSON
  ↓ Pydantic 解析为 LearningPlan
  ↓ current_node_id = 第一个节点
  ↓ state = "studying"
  ↓
store.save_plan() → workspace/progress/plan.json
```

### 4.2 资源获取流程

```
用户: rl-agent fetch
  ↓ Librarian.fetch_for_node(node)
  ↓ chat_json: 推荐 arxiv queries / repos / blogs / YouTube
LLM 返回: 资源清单 JSON
  ↓
并行循环:
  ├── arxiv (库 search → 下 PDF → fallback httpx)
  ├── git clone --depth 1 --timeout 120
  ├── httpx + BeautifulSoup 抓博客
  └── youtube-transcript-api 扒字幕
  ↓
每条都 append_resource() 到 resources.jsonl
（任何一条失败都生成「失败 Resource」记录，不阻断其他抓取）
```

### 4.3 答疑流程（RAG 增强）

```
用户: rl-agent ask "<question>"
  ↓ append_trajectory(kind="ask")
  ↓ Tutor.ask(node, question)
    ├── rag.retrieve(question)
    │   ├── BM25 召回 top-12
    │   └── LLM rerank → top-5
    ├── load_trajectory(node.id, limit=12)  # 历史 Q&A
    └── chat_multi(system=节点上下文+RAG片段, messages=历史+本次)
  ↓ append_trajectory(kind="answer", meta={citations})
返回: (answer, citations)
```

### 4.4 自测流程

```
用户: rl-agent test
  ↓ Examiner.generate_exercises(node)
    ├── rag.retrieve(节点关键词)
    └── chat_json → 5 题（concept×2 / derivation / code-debug / discussion）
  ↓ state = "self_testing", save_plan
  ↓
逐题循环:
  ├── 显示题目
  ├── 用户答（支持多行）
  └── Examiner.grade_answer → ExerciseAttempt(score, feedback)
  ↓
summarize_session() → avg score + verdict
append_exercise(session)
append_trajectory(kind="test", meta={score})
  ↓
若 avg ≥ 0.8: state = "advancing"
若 avg < 0.8: state = "studying"
```

### 4.5 推进流程

```
用户: rl-agent advance
  ↓ orchestrator.mark_node_completed(plan, current_node_id)
  ↓ orchestrator.advance_to_next(plan)
    ├── 找下一个 pending 节点
    ├── current_node_id = next.id
    ├── next.status = "in_progress"
    └── 若无下一个: state = "done"
```

---

## 5. 接口契约（CLI · HTTP · Agent）

### 5.1 CLI 命令清单（28 个）

| 分类 | 命令 |
|------|------|
| **计划** | `plan <goal>` `status` `goto <id>` `advance` `trajectory [id]` |
| **资源** | `fetch` `fetch-blog <url>` `fetch-youtube <url\|id>` `resources [id]` |
| **学习** | `ask "<q>"` `practices` |
| **自测** | `test` |
| **知识库** | `archive [id\|--all-completed\|--all-active]` `kb [id]` |
| **复盘** | `review-weekly` `review-stage <id>` |
| **RAG** | `index` `query "<q>"` |
| **工作区** | `workspace list/create/switch/current/rename/delete` |
| **服务** | `serve [--host --port]` `daemon [--idle-days]` |

### 5.2 HTTP API（部分关键路由）

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/health` | 健康检查 + provider 信息 |
| GET | `/api/plan` | 获取当前计划 |
| POST | `/api/plan` | 生成新计划 |
| POST | `/api/goto` | 切换当前节点 |
| POST | `/api/ask` | 答疑（带引用） |
| POST | `/api/practices` | 行业最佳实践 |
| POST | `/api/courseware` | 生成课件 |
| GET | `/api/courseware/{node_id}` | 读已生成课件 |
| POST | `/api/test/start` | 开始自测 |
| POST | `/api/test/grade` | 单题评分 |
| POST | `/api/test/submit` | 提交整场 |
| POST | `/api/advance` | 推进到下一节点 |
| POST | `/api/index` | 重建 RAG 索引 |
| GET | `/api/index/stats` | 索引统计 |
| POST | `/api/query` | 直接 RAG 查询 |
| POST | `/api/fetch` | 抓资源 |
| GET | `/api/resources/{node_id}` | 节点资源列表 |
| POST | `/api/archive` | 蒸馏 KB |
| GET | `/api/kb` | KB 索引 |
| GET | `/api/kb/{node_id}` | 节点 KB |
| POST | `/api/review/weekly` | 周复盘 |
| GET | `/api/trajectory` | 学习轨迹 |
| GET | `/api/stats` | 综合统计 |
| GET/POST/DELETE | `/api/workspaces[/...]` | 工作区 CRUD |
| GET | `/` | 内嵌 HTML 单页应用 |

### 5.3 Agent 接口契约

每个 Agent 暴露 1-2 个公开函数，签名稳定：

```python
# planner.py
def make_plan(goal: str, level: str = "") -> LearningPlan

# librarian.py
def fetch_for_node(node: LearningNode) -> list[Resource]

# tutor.py
def ask(node, stage_name, question, history_limit=6, use_rag=True)
    -> tuple[str, list[dict]]   # (answer, citations)

# examiner.py
def generate_exercises(node, use_rag=True) -> list[ExerciseQuestion]
def grade_answer(q, answer) -> ExerciseAttempt
def summarize_session(attempts) -> tuple[float, str]

# practice.py
def best_practices(node) -> str

# courseware.py
def generate_courseware(node, stage_name="") -> dict

# archivist.py
def archive_node(node, stage_name="", use_rag=True) -> Path
def archive_all(plan, only_completed=False) -> list[Path]
def build_index(plan) -> Path

# reviewer.py
def weekly_review(plan) -> Path
def stage_review(plan, stage_id) -> Path
```

---

## 6. RAG 子系统设计

### 6.1 索引阶段

```python
chunk_pdf(pdf_path):
    pages = pymupdf.extract_pages()        # 每页 (page_no, text)
    title = doc.metadata.title || filename
    toc = doc.get_toc()                     # PDF 大纲
    if toc:
        sections = split_by_toc(pages, toc)
    else:
        sections = split_by_regex(pages)    # 正则识别 Abstract/Method/...
    chunks = []
    for sec in sections:
        for part in split_long(sec, MAX=3500, OVERLAP=200):
            if len(part) >= MIN=200:
                chunks.append(Chunk(...))
    return chunks
```

**分词器（同时用于索引和查询）**：

```python
def tokenize(text):
    text = text.lower()
    out = re.findall(r'[A-Za-z0-9_]+', text)        # 英文词
    cjk = re.findall(r'[一-鿿]+', text)
    if cjk:
        for blob in cjk:
            out.extend(jieba.lcut(blob))            # 中文词
    return [t for t in out if t not in STOPWORDS and len(t) > 1]
```

**BM25 索引**：

```python
corpus = [tokenize(c.text) for c in chunks]
bm25 = BM25Okapi(corpus)
pickle.dump({"bm25": bm25, "ids": [c.chunk_id for c in chunks]}, ...)
```

### 6.2 检索阶段

```python
retrieve(query, top_k_bm25=12, top_n=5, rerank=True):
    hits = bm25_search(query, top_k=12)
    if rerank and len(hits) > top_n:
        hits = llm_rerank(query, hits, top_n=5)
    return hits[:top_n]
```

**LLM rerank 失败时降级为 BM25 原始顺序**——RAG 子系统的容错原则是「弱于不可用」。

### 6.3 引用注入

每个 hit 渲染为：

```
--- CITATION [doc_id · §section · p.N] ---
Title: PPO Algorithms
Section: 3. Method
<chunk text>
```

prompt 强约束：
- 只能引用列出的 chunk_id
- 没匹配上要明说「(no library match)」
- 禁止凭空捏造引用

---

## 7. LLM 抽象与容错

### 7.1 Provider 抽象

```python
LLM_PROVIDER = "anthropic" | "openrouter"

def chat(system, user, model=None, max_tokens=4096, temperature=0.3) -> str
def chat_multi(system, messages, max_tokens=4096, temperature=0.4) -> str
def chat_json(system, user, max_tokens=4096, max_attempts=3) -> dict
```

### 7.2 三层容错

| 层级 | 触发 | 策略 |
|------|------|------|
| **网络层** | `RemoteProtocolError` / `ConnectTimeout` / `APIConnectionError` 等 | 指数退避 3 次：2s → 4s → 8s |
| **JSON 层** | `chat_json` 解析失败 | ① 去 ```fence``` ② 控制字符转义 ③ 整次重试（max_tokens 递增 +1024） |
| **业务层** | 单个资源抓取失败 | 记录「失败 Resource」，不阻断其他 |

### 7.3 OpenRouter 兼容

把 Anthropic 风格的 `system + messages` 适配为 OpenAI 风格的 `messages = [{role: system}, ...]`，5xx 错误识别为可重试。

---

## 8. 存储与配置

### 8.1 配置层级

```
1. 环境变量 WORKSPACE_DIR (强制覆盖) → 用于 daemon / launchd 固定 workspace
2. WORKSPACES_ROOT/.active (运行时切换) → CLI 用户的常规切换路径
3. ./workspace/ (legacy fallback) → 老版本单 workspace 兼容
4. workspaces/default/ (默认创建)
```

`config.WORKSPACE_DIR` 是模块属性，`workspace_path()` 每次调用读最新值，所以 CLI 切换工作区不用重启进程。

### 8.2 持久化

- **plan.json**：单文件覆盖写。Pydantic `model_dump_json(indent=2)` 序列化。
- **trajectory.jsonl / resources.jsonl / exercises.jsonl**：追加写，每行一条 JSON。
- **library/notes/*.md**：直接写文本，文件名 = `<node_id>_<slug>.md`。
- **library/index/bm25.pkl**：pickle，因为 `BM25Okapi` 对象有 numpy 数组。

### 8.3 幂等

- 已下载的 arxiv PDF 检测文件存在则跳过
- 已 clone 的 GitHub 仓库检测目录存在则跳过
- archive 同名 KB 文件直接覆盖
- `migrate_legacy()` 检测到目标已存在则跳过

---

## 9. 并发与一致性

**当前设计**：单进程同步执行。

| 场景 | 现状 | 风险 |
|------|------|------|
| CLI 单次命令 | ✅ 安全 | 无 |
| Web UI 多浏览器标签 | ⚠️ 同时写 jsonl 可能出问题 | 单用户场景概率低 |
| Daemon + Web UI 并存 | ⚠️ 都修改 plan.json | 需要文件锁（未实现） |

**容忍度**：单用户工具，并发冲突极低，未引入 fcntl 锁。

---

## 10. 部署方案

### 10.1 三种部署形态

| 方案 | 文件 | 适用 |
|------|------|------|
| 原生 macOS | `com.rlagent.{web,daemon}.plist` + `install-native.sh` | Mac 用户 |
| 原生 Linux | `rl-agent-{web,daemon}.service` (user systemd) | Linux 用户 |
| Docker | `Dockerfile` + `docker-compose.yml` | 需要跨机迁移 |

### 10.2 远程访问

- **同一 Wi-Fi**：把 `--host 127.0.0.1` 改为 `0.0.0.0`，警告需要套 nginx basic auth
- **公网**：推荐 Tailscale（零配置 mesh VPN）
- **不推荐**：公网直接暴露（无认证机制）

### 10.3 健康检查

```
GET /api/health → {"ok":true, "provider": "Anthropic · claude-opus-4-5"}
```

---

## 11. 安全与隐私

### 11.1 API Key 管理

- `.env` 在 `.gitignore` 中
- `.env.example` 是模板（不含真实 key）
- launchd plist / systemd unit 通过 `WorkingDirectory` 让进程能加载 `.env`

### 11.2 输入验证

- workspace 名字正则限制：`^[a-z0-9][a-z0-9_-]{0,39}$`
- `git clone` 限定 `--depth 1` + `timeout 120`，避免大仓库阻塞
- httpx 带 `User-Agent`，超时 30s
- 用户答题输入直接传 LLM 评分，无 SQL/XSS 风险

### 11.3 版权合规

- 仅抓 arxiv 预印本 + GitHub 公开仓
- Librarian 系统提示明确写「only suggest things you are confident exist」
- 闭源材料用户手动放进 `library/papers/` 后，Agent 才能用

### 11.4 隐私

- 所有数据本地，不上报
- LLM 调用是数据出口，但用户主动选择 provider
- Web UI 默认 bind `127.0.0.1`，外暴露需要用户主动改

---

## 12. 可观测性

### 12.1 日志

- CLI：rich 控制台输出
- Web UI：uvicorn 默认日志
- Daemon：launchd / systemd journal
- LLM 重试：`print(f"[llm] {label} attempt N/M failed: ...")`

### 12.2 学习轨迹

`trajectory.jsonl` 是用户视角的完整审计：

```json
{"ts": "2026-05-25T14:23:11", "node_id": "1.2", "kind": "ask",
 "content": "PPO clip ratio 是怎么推出来的?", "meta": {}}
{"ts": "2026-05-25T14:23:38", "node_id": "1.2", "kind": "answer",
 "content": "...", "meta": {"citations": [{"doc_id": "1707.06347_PPO", ...}]}}
```

### 12.3 指标

`/api/stats` 返回综合统计（plan 进度、节点数、资源数等）。**目前无 Prometheus / OTel**，单用户场景不需要。

---

## 13. 设计权衡

| 选择 | 替代方案 | 为什么这么选 |
|------|----------|-------------|
| 文件 + JSONL | SQLite / Postgres | 单用户够用，可 git，可手改 |
| BM25 | 向量检索（FAISS / Chroma） | 中英混合表现稳，无 embedding 调用成本 |
| 同步调用 | asyncio | 用户感知不到延迟，调试简单 |
| 单 prompt per Agent | function calling / 工具协议 | 提示工程足够，复杂度低 |
| 本地内嵌 HTML | Vite + React | 0 构建步骤，部署简单 |
| typer + rich | argparse | 美化输出 + 自动 --help |
| pymupdf | pdfplumber / pdfminer | 速度最快，TOC 提取好 |
| jieba | THULAC / pkuseg | 体积小，免训练 |
| APScheduler | cron / system timer | 跨平台，纯 Python |
| Anthropic + OpenRouter | 单一 provider | 防供应商绑定 |

---

## 14. 已知限制与遗留问题

### 14.1 设计层

- **Orchestrator 偏弱**：只做状态转换，没有"自动驱动"逻辑（自动 fetch、自动 test）；用户仍需手动逐命令推进。
- **`reviewing` 状态没用**：定义了但代码里没人转入。
- **没有 Reviewer 自动触发**：阶段全完成时不会自动生成 stage review，依赖用户手动 `review-stage`。
- **RAG 注入散落三处**：`tutor.py` / `examiner.py` / `archivist.py` 都各自调用 `rag.retrieve + render_context`，可抽公共 helper。

### 14.2 工程层

- **无文件锁**：多进程同时写 jsonl 理论上有风险（Web UI + Daemon 并发场景）。
- **无单元测试**：仅 `tests/smoke_test.py` 一个端到端验证；没有 Agent 级别的 mock 测试。
- **CLI 无 `--dry-run`**：fetch 命令一旦运行就会真下 PDF，不能先看推荐了什么。
- **PDF 解析失败不上报到 trajectory**：indexer 只 print，不留痕迹。
- **Web UI 把 1100 行 HTML 内嵌在 `server.py`**：不利维护，但部署最简单。

### 14.3 体验层

- **首次 fetch 慢**：arxiv 搜+下、git clone、blog 抓都是串行，单次可达 1-2 分钟。
- **LLM 失败仍可能阻断**：3 次重试都败时直接抛异常，CLI 无优雅降级。
- **RAG 索引手动触发**：fetch 完不会自动 index，需要用户 `rl-agent index`。

### 14.4 计划改进

| 优先级 | 改进 | 收益 |
|--------|------|------|
| P0 | 加文件锁（fcntl on POSIX） | 消除并发写风险 |
| P1 | fetch 完自动触发 index | 用户体验直球 |
| P1 | RAG 注入抽 `with_rag(prompt)` 装饰器 | 减少重复代码 |
| P1 | Orchestrator 加自动转推（每节点 fetch → study → test → advance） | 真正的"主动驱动" |
| P2 | Reviewer 阶段完成自动触发 | 兑现「Agent 主动」承诺 |
| P2 | Web UI 拆出独立前端 | 维护成本下降 |
| P2 | Agent 单测 + LLM mock | 回归保护 |

---

_本技术设计文档反映 v0.3.0 的真实代码形态。后续修改请同时更新本文档和 PRD。_
