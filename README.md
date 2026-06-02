# RL Agent Tutor

一个本地运行的自主学习 Agent,专门用来学 RL / LLM 后训练 / Agent 方向。
它不只回答问题——它**主动驱动**你的学习闭环:规划 → 取资源 → 答疑 → 自测 → 反馈 → 推进。

---

## 它能做什么

- **路径规划**:给一个目标,产出 4–6 阶段、每阶段 3–5 节点的可执行计划,每个节点有可验证的产出标准
- **资源获取**:默认从 arxiv / GitHub / YouTube / Web / 本地目录获取资源,也支持按工作区配置自定义 source
- **结构化课件**:把资源转成 Courseware JSON,支持段落、表格、公式、代码、图解、视频片段和检查点问题
- **答疑互动**:Tutor 带着节点上下文 + 历史对话回答,不寒暄、不啰嗦
- **自测反馈**:每个节点 5 题(概念辨析 / 推导 / 代码 debug / 讨论),AI 评分 + 给具体改进建议
- **证据链**:资源会记录是否被课件、引用、自测、归档使用过,避免只囤资料不用
- **今日任务**:Web 首页给出唯一推荐下一步,例如抓资源、生成课件、开始自测、补弱或推进
- **能力看板**:展示掌握节点、薄弱节点、资源利用率、平均自测分和估时进度
- **行业最佳实践**:从"踩过坑的工程师"角度给 must-do、common mistakes、preferred tools
- **状态机驱动**:Agent 知道你在哪、上一步做得怎样、下一步该干什么——不是工具集

---

## 5 分钟跑起来

### 1. 准备

```bash
# 需要 Python 3.11+
python --version

# 进入项目目录
cd rl-agent-tutor

# 安装(开发模式,可改代码立即生效)
pip install -e .
```

### 2. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env,填入你的 ANTHROPIC_API_KEY
```

### 3. 第一次使用

如果想用浏览器界面,先启动 Web UI:

```bash
rl-agent-web
# 默认访问 http://127.0.0.1:8765

# 兼容入口,等价于上面:
rl-agent serve
```

命令行闭环也可以直接使用:

```bash
# 生成学习计划
rl-agent plan "掌握 PPO 并能用 TRL 跑通 RLHF 流水线" --level "深度学习熟练,RL 零基础"

# 看看现在该做什么
rl-agent status

# 为当前节点抓资源(arxiv PDF + GitHub clone)
rl-agent fetch

# 看抓到了啥
rl-agent resources

# 问问题
rl-agent ask "PPO 的 clip 操作具体限制了什么?"

# 看行业最佳实践
rl-agent practices

# 觉得学得差不多了,自测
rl-agent test

# 推进到下一节点
rl-agent advance
```

---

## 命令一览

| 命令 | 作用 |
|---|---|
| `rl-agent plan "<目标>"` | 生成学习计划(已有计划会询问是否覆盖) |
| `rl-agent status` | 看计划全貌 + 当前节点 + 下一步建议 |
| `rl-agent fetch` | 为当前节点抓资源(arxiv + GitHub) |
| `rl-agent resources [node_id]` | 列出某节点已抓到的资源 |
| `rl-agent ask "<问题>"` | 向 Tutor 提问(自动带节点上下文) |
| `rl-agent practices` | 当前节点的行业最佳实践 |
| `rl-agent test` | 当前节点的 5 题自测(交互式) |
| `rl-agent advance` | 把当前节点标记完成,跳到下一节点 |
| `rl-agent goto <node_id>` | 跳到指定节点(跳过 / 回头) |
| `rl-agent trajectory [node_id]` | 看学习轨迹流水 |
| `rl-agent serve [--host 127.0.0.1] [--port 8765] [--reload]` | 从主 CLI 启动本地 Web UI |
| `rl-agent-web [--host 127.0.0.1] [--port 8765] [--reload]` | 独立 Web UI 入口 |
| `rl-agent workspace list/create/switch/current/rename/delete` | 管理多个学习工作区 |
| `rl-agent archive [node_id]` | 把学习轨迹、资源和自测整理成知识库 Markdown |
| `rl-agent kb [node_id]` | 查看知识库索引或某节点笔记 |
| `rl-agent index` | 为本地 PDF 建 RAG 索引 |
| `rl-agent query "<问题>"` | 搜索本地 PDF 索引 |

---

## Web UI

Web 入口由 FastAPI 提供,静态文件在 `src/rl_agent_tutor/web/`。

```bash
rl-agent-web
# 或
rl-agent serve --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765` 后可以在浏览器里完成计划、资源抓取、答疑、自测、归档、RAG 检索和工作区切换。

如果要用 `uvicorn` 直接启动:

```bash
uvicorn rl_agent_tutor.server:create_app --factory --host 127.0.0.1 --port 8765
```

局域网访问时可以把 `--host` 改成 `0.0.0.0`,但这个应用默认没有登录认证。暴露到局域网或远程前,建议先加反向代理认证或放到 Tailscale 等私有网络里。

---

## 测试验证

默认测试集不调用真实 LLM / 网络,适合作为本地回归:

```bash
pytest -q
python -m compileall -q src/rl_agent_tutor tests
node --check src/rl_agent_tutor/web/app.js
```

Web UI 的源码在 `src/rl_agent_tutor/web/`。`src/rl_agent_tutor/static/index.html` 是生成产物,不要手改。修改 `web/index.html`、`web/style.css` 或 `web/app.js` 后运行:

```bash
python scripts/build_static.py
```

`pytest -q` 会检查生成产物是否和源码一致。

新增能力的组合回归在 `tests/api/test_capability_regression.py` 中,覆盖:

- 自定义资源源加载
- 今日任务推荐动作
- 结构化课件返回
- 资源证据链状态推进
- 自测提交后的掌握度变化
- 能力看板数据

真实端到端 smoke 测试默认跳过,需要显式开启:

```bash
RUN_SMOKE_TESTS=1 pytest tests/smoke_test.py
```

这组测试会真实调用 LLM、可能访问 arxiv/GitHub,需要已配置 `ANTHROPIC_API_KEY` 或 OpenRouter,并会在项目下创建 `workspace_smoketest/`。

---

## 数据存储

所有数据存在本地 `workspace/` 目录(可通过 `.env` 的 `WORKSPACE_DIR` 改路径):

```
workspace/
├── library/
│   ├── papers/      # arxiv PDF
│   ├── code/        # git clone 的仓库
│   └── notes/       # AI 生成的精读笔记(后续版本)
└── progress/
    ├── plan.json         # 当前学习计划 + 状态
    ├── trajectory.jsonl  # 所有学习活动流水
    ├── resources.jsonl   # 资源索引
    └── exercises.jsonl   # 自测记录
```

文件全是人类可读的 JSON / JSONL,**纯文本可备份、可 git 跟踪、可手改**。

## 资源源配置

`rl-agent fetch` 默认会从 arxiv、GitHub、YouTube、网页文章和本地资料目录推荐资源。你可以在当前工作区新增 `config/sources.yaml` 覆盖默认源或追加自定义源:

```yaml
defaults:
  enabled:
    - arxiv
    - github
    - youtube
    - website

custom_sources:
  - id: hf-blog
    type: rss
    name: Hugging Face Blog
    url: https://huggingface.co/blog/feed.xml
    priority: core

  - id: local-papers
    type: local_directory
    name: Local Papers
    path: library/manual/papers
    priority: core
```

当前版本会把启用的资源源注入推荐提示,并在抓取结果中记录 `source_id` 和 `priority`。后续版本会把每类 source provider 拆成独立抓取器。

## 学习闭环数据

资源现在带有生命周期字段:

| 字段 | 说明 |
|---|---|
| `source_id` | 来自哪个默认或自定义资源源 |
| `priority` | `core` / `normal` / `supplemental` |
| `status` | `fetched` / `read` / `cited` / `tested` / `archived` / `rejected` |
| `used_by` | 被课件、Tutor 引用、自测或归档使用的证据 |

课件会同时保存:

```text
library/notes/courseware/<node>_<slug>.md
library/notes/courseware/<node>_<slug>.json
```

`.json` 是结构化课件数据,Web UI 优先渲染它;`.md` 保持纯文本可读和导出兼容。

---

## 版权边界

- **自动下载**:仅限作者主动公开的源(arxiv 预印本、GitHub 公开仓库)
- **不会做**:绕过付费墙抓闭源期刊 PDF、Sci-Hub 等灰色源
- **闭源资源**:Agent 给链接 + 你已合法获取的 PDF 可手动放进 `workspace/library/papers/`,Agent 可以基于它出题、答疑

---

## 接下来的版本(MVP 之后)

按周迭代:

- **知识地图**:自动从计划、资源和归档笔记生成可视化学习地图
- **导出能力**:导出整个学习成果包,便于备份、复盘或分享
- **通知增强**:更细粒度的提醒策略和复习计划

---

## 故障排查

**`ANTHROPIC_API_KEY not set`** — 检查 `.env` 文件是否在项目根目录、是否填了 key。

**Anthropic 403 `Request not allowed`** — key 通了,但当前账号/项目无权访问 `.env` 里的模型。把 `.env` 中的 `ANTHROPIC_MODEL` 改成可用模型,例如:

```bash
ANTHROPIC_MODEL=claude-sonnet-4-5
```

改完后重启 `rl-agent-web`。

**`git not installed`** — librarian 会跳过 clone,只记录链接。装 git 后再 `rl-agent fetch` 就行。

**arxiv 下载慢/失败** — 多试几次,arxiv 偶尔抖动。已下载的论文不会重复抓。

**JSON 解析失败** — LLM 偶尔不守规矩。重跑命令通常能好;持续失败请用 `--model claude-opus-4-5`(在 `.env` 里改 `ANTHROPIC_MODEL`)。

---

## 项目结构

```
rl-agent-tutor/
├── pyproject.toml
├── .env.example
├── README.md
└── src/rl_agent_tutor/
    ├── cli.py            # typer CLI 入口
    ├── server.py         # FastAPI Web 入口(create_app / rl-agent-web)
    ├── config.py         # 环境变量与工作区
    ├── models.py         # Pydantic 数据模型
    ├── store.py          # 文件持久化
    ├── llm.py            # Anthropic 封装
    ├── services/         # CLI 和 API 共享的业务服务
    ├── routes/           # FastAPI 路由
    ├── web/              # 浏览器端静态资源
    ├── planner.py        # 路径规划 Agent
    ├── librarian.py      # 资源获取 Agent
    ├── tutor.py          # 答疑 Agent
    ├── examiner.py       # 评测 Agent
    ├── archivist.py      # 知识库归档 Agent
    ├── reviewer.py       # 周期/阶段复盘 Agent
    └── practice.py       # 最佳实践 Agent
```
