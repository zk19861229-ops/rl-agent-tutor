# RL Agent Tutor — 架构文档

> 本文档基于代码本体（v0.3.0）整理。CLI 28 个命令、FastAPI 50+ 路由、9 个 Agent，但底层抽象是清晰的：**状态机 + Agent 工厂 + 本地文件存储 + RAG 横切**。

## 目录

- [图 1：分层架构](#图-1分层架构三层--三种交付形态)
- [图 2：学习闭环 Agent 协作（时序图）](#图-2学习闭环-agent-协作时序图)
- [图 3：状态机（Plan + Node 双层）](#图-3状态机plan--node-双层)
- [图 4：数据流 + 工作区目录结构](#图-4数据流--工作区目录结构)
- [图 5：RAG 管线](#图-5rag-管线最复杂的子系统)
- [架构层面值得注意的设计点](#架构层面值得注意的设计点)

---

## 图 1：分层架构（三层 + 三种交付形态）

```mermaid
graph TB
    subgraph DELIVERY["🎯 交付层 (User-facing)"]
        CLI["CLI<br/>typer + rich<br/>cli.py"]
        WEB["Web UI<br/>FastAPI + 内嵌 HTML<br/>server.py"]
        DAEMON["Daemon<br/>APScheduler<br/>scheduler.py"]
    end

    subgraph AGENTS["🤖 Agent 层 (有状态机)"]
        ORC["Orchestrator<br/>状态机驱动"]
        PLAN["Planner<br/>规划"]
        LIB["Librarian<br/>资源获取"]
        TUT["Tutor<br/>答疑"]
        EXM["Examiner<br/>出题/评分"]
        PRAC["Practice<br/>最佳实践"]
        CW["Courseware<br/>课件合成"]
        ARC["Archivist<br/>知识库蒸馏"]
        REV["Reviewer<br/>周/阶段复盘"]
    end

    subgraph CORE["🛠️ 核心服务层"]
        LLM["llm.py<br/>Anthropic / OpenRouter<br/>JSON 修复 + 重试"]
        RAG["rag.py + indexer.py<br/>BM25 + LLM rerank"]
        FETCH["fetchers.py<br/>arxiv / GitHub / blog / YT"]
        STORE["store.py<br/>JSON/JSONL 持久化"]
        WS["workspaces.py<br/>多工作区切换"]
    end

    subgraph STORAGE["💾 存储层 (本地文件)"]
        PROG["progress/<br/>plan.json<br/>trajectory.jsonl<br/>resources.jsonl<br/>exercises.jsonl"]
        LIBR["library/<br/>papers/ code/ notes/<br/>index/ courseware/<br/>reviews/ nudges/"]
    end

    subgraph EXT["🌐 外部依赖"]
        ANT["Anthropic API"]
        OR["OpenRouter API"]
        ARXIV["arxiv.org"]
        GH["GitHub.com"]
        BLOG["Blog HTML"]
        YT["YouTube"]
    end

    CLI --> ORC
    WEB --> ORC
    DAEMON --> REV
    DAEMON --> ARC

    ORC --> PLAN & LIB & TUT & EXM & PRAC & CW & ARC & REV

    PLAN --> LLM
    TUT --> LLM & RAG
    EXM --> LLM & RAG
    PRAC --> LLM
    CW --> LLM
    ARC --> LLM & RAG
    REV --> LLM
    LIB --> LLM & FETCH

    LLM --> ANT & OR
    FETCH --> ARXIV & GH & BLOG & YT
    RAG --> LIBR

    ORC & PLAN & LIB & TUT & EXM & ARC & REV --> STORE
    STORE --> PROG
    LIB --> LIBR
    CW --> LIBR
    ARC --> LIBR
    REV --> LIBR
    WS -.切换.-> STORE
```

---

## 图 2：学习闭环 Agent 协作（时序图）

```mermaid
sequenceDiagram
    autonumber
    actor U as 用户
    participant CLI
    participant ORC as Orchestrator
    participant P as Planner
    participant L as Librarian
    participant IDX as Indexer
    participant T as Tutor
    participant R as RAG
    participant E as Examiner
    participant LLM
    participant FS as 本地文件

    U->>CLI: rl-agent plan "目标"
    CLI->>P: make_plan(goal, level)
    P->>LLM: 系统提示+目标 → JSON 计划
    LLM-->>P: 4-6 阶段结构
    P->>FS: save plan.json
    ORC->>FS: state=studying

    U->>CLI: rl-agent fetch
    CLI->>L: fetch_for_node(node)
    L->>LLM: 推荐资源 (arxiv/repo/blog/yt)
    LLM-->>L: 资源清单 JSON
    L->>L: 下 PDF / clone / 抓 HTML / 扒字幕
    L->>FS: append resources.jsonl + 文件落盘

    U->>CLI: rl-agent index
    CLI->>IDX: index_papers()
    IDX->>FS: 解析 PDF → chunks.jsonl + bm25.pkl

    U->>CLI: rl-agent ask "问题"
    CLI->>T: ask(node, question)
    T->>R: retrieve(question)
    R->>FS: BM25 召回 top-K
    R->>LLM: rerank → top-N
    R-->>T: 命中片段 + 引用
    T->>FS: 读历史对话 trajectory
    T->>LLM: 上下文+RAG片段+历史+问题
    LLM-->>T: 答案 (带引用)
    T->>FS: append trajectory (ask + answer)

    U->>CLI: rl-agent test
    CLI->>E: generate_exercises(node)
    E->>R: retrieve(节点关键词)
    E->>LLM: 出 5 题
    loop 每道题
        U->>CLI: 答题
        CLI->>E: grade_answer
        E->>LLM: 评分+反馈
    end
    E->>FS: append exercises.jsonl

    alt avg ≥ 0.8
        ORC->>FS: state=advancing
        U->>CLI: rl-agent advance
        CLI->>ORC: mark_completed + advance_to_next
    else avg < 0.8
        ORC->>FS: state=studying (回炉)
    end
```

---

## 图 3：状态机（Plan + Node 双层）

```mermaid
stateDiagram-v2
    direction LR
    [*] --> planning: rl-agent plan

    state "Plan State" as PS {
        planning --> studying: 计划生成完成
        studying --> self_testing: rl-agent test
        self_testing --> advancing: avg ≥ 0.8
        self_testing --> studying: avg < 0.8 (回炉)
        advancing --> studying: rl-agent advance<br/>(还有 pending 节点)
        advancing --> done: 所有节点完成
        studying --> reviewing: 阶段全完成
        reviewing --> studying: 进入下一阶段
    }

    state "Node State" as NS {
        [*] --> pending
        pending --> in_progress: 成为 current_node
        in_progress --> self_testing: 出题
        self_testing --> in_progress: 分数不达标
        self_testing --> completed: 分数达标 + advance
        in_progress --> completed: 直接 advance
        completed --> [*]
    }
```

---

## 图 4：数据流 + 工作区目录结构

```mermaid
flowchart LR
    subgraph IN["📥 外部输入"]
        U1["用户目标"]
        U2["用户问题"]
        U3["用户答题"]
        EX1["arxiv 论文"]
        EX2["GitHub 仓库"]
        EX3["博客文章"]
        EX4["YouTube 字幕"]
    end

    subgraph TR["⚙️ Agent 转换层"]
        T1["Planner 结构化"]
        T2["Librarian 抓取"]
        T3["Indexer 切块"]
        T4["Tutor RAG"]
        T5["Examiner 评分"]
        T6["Archivist 蒸馏"]
        T7["Reviewer 复盘"]
    end

    subgraph WS["💾 workspace/ 目录"]
        direction TB
        subgraph PR["progress/"]
            P1["plan.json<br/>(状态)"]
            P2["trajectory.jsonl<br/>(全活动流)"]
            P3["resources.jsonl"]
            P4["exercises.jsonl"]
        end
        subgraph LB["library/"]
            L1["papers/*.pdf"]
            L2["code/<repo>/"]
            L3["notes/blogs/*.md"]
            L4["notes/transcripts/*.md"]
            L5["index/chunks.jsonl<br/>index/bm25.pkl"]
            L6["notes/courseware/*.md"]
            L7["notes/*.md<br/>(KB)"]
            L8["notes/INDEX.md"]
            L9["notes/reviews/*.md"]
            L10["notes/nudges/*.md"]
        end
    end

    U1 --> T1 --> P1
    U2 --> T4 --> P2
    U3 --> T5 --> P4

    EX1 --> T2 --> L1
    EX2 --> T2 --> L2
    EX3 --> T2 --> L3
    EX4 --> T2 --> L4

    L1 --> T3 --> L5
    L5 -.检索.-> T4
    L5 -.检索.-> T5

    P2 & P3 & P4 & L1 & L2 & L3 & L4 --> T6 --> L7
    L7 --> L8

    P2 & P4 --> T7 --> L9
```

---

## 图 5：RAG 管线（最复杂的子系统）

```mermaid
flowchart TB
    subgraph IDX["📚 索引阶段 (rl-agent index)"]
        direction TB
        A1["遍历 library/papers/*.pdf"]
        A2["pymupdf 提取每页文本"]
        A3{"有 TOC?"}
        A4["TOC 切 section"]
        A5["正则识别<br/>Abstract/Method/...<br/>切 section"]
        A6["按 3500 字符上限<br/>+ 200 字符 overlap<br/>再切 chunk"]
        A7["jieba + 正则<br/>分词 + 去停用词"]
        A8["BM25Okapi 建索引"]
        A9[("chunks.jsonl<br/>bm25.pkl")]

        A1 --> A2 --> A3
        A3 -->|是| A4
        A3 -->|否| A5
        A4 --> A6
        A5 --> A6
        A6 --> A7 --> A8 --> A9
    end

    subgraph RET["🔍 检索阶段 (Tutor/Examiner/Archivist 调用)"]
        direction TB
        B1["query (节点描述/用户问题)"]
        B2["tokenize<br/>(同索引器)"]
        B3["BM25 打分<br/>top-K=12"]
        B4{"hits 数 > top-N?"}
        B5["LLM rerank<br/>(给 chunk_id 列表)"]
        B6["按 max_chars=8000<br/>渲染 context"]
        B7["回答时强制引用<br/>[doc_id · §sec · p.N]"]

        B1 --> B2 --> B3 --> B4
        B4 -->|是| B5
        B4 -->|否| B6
        B5 --> B6 --> B7
    end

    subgraph PROMPT["💬 注入到 prompt"]
        C1["Tutor 系统提示<br/>+ Local library passages 块<br/>+ 历史对话"]
        C2["Examiner 系统提示<br/>+ Local library excerpts 块"]
        C3["Archivist 系统提示<br/>+ Library excerpts 块"]
    end

    A9 -.加载.-> B3
    B7 --> C1 & C2 & C3
```

---

## 架构层面值得注意的设计点

1. **Orchestrator 实际很轻** —— 只负责状态转换，不调用 Agent；真正的「协作」是用户驱动的（CLI 命令逐个触发各 Agent）。

2. **Daemon 才是真正的"主动 Agent"** —— APScheduler 定时跑 Reviewer 和 Archivist，完成 README 里说的"Agent 主动驱动"承诺。

3. **RAG 是后加的横切关注点** —— Tutor / Examiner / Archivist 三处都注入相同的 `rag.retrieve + render_context` 调用，没抽公共装饰器（可以重构）。

4. **多工作区是运行时切换的** —— `config.WORKSPACE_DIR` 是模块属性，`workspace_path()` 每次调用读最新值，所以 CLI 切换工作区不用重启进程；但 `serve` 进程因为 uvicorn 缓存，切换后必须重启（README 部署文档明确提到了）。

5. **LLM 容错策略分三层** ——
   - 网络层：`_retry` 指数退避 3 次（仅对瞬态错误）
   - JSON 层：`chat_json` 三段救援（去 fence、控制字符转义、最多 3 次重试）
   - 业务层：每个 Agent 接受 LLM 的部分失败（缺资源就跳过、缺字幕就降级）

6. **状态机覆盖不全** —— `reviewing` 状态在代码中只是文档化，没有命令真正把 plan 推进到这个状态；阶段完成事件没有自动触发器，依赖用户手动 `review-stage`。

---

_最后更新：2026-05-25。基于 commit `82e3bf1`。_
