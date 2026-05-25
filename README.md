# RL Agent Tutor

一个本地运行的自主学习 Agent,专门用来学 RL / LLM 后训练 / Agent 方向。
它不只回答问题——它**主动驱动**你的学习闭环:规划 → 取资源 → 答疑 → 自测 → 反馈 → 推进。

---

## 它能做什么

- **路径规划**:给一个目标,产出 4–6 阶段、每阶段 3–5 节点的可执行计划,每个节点有可验证的产出标准
- **资源获取**:自动从 arxiv 下载论文 PDF、git clone 推荐代码仓库到本地 `library/`(开放源全自动)
- **答疑互动**:Tutor 带着节点上下文 + 历史对话回答,不寒暄、不啰嗦
- **自测反馈**:每个节点 5 题(概念辨析 / 推导 / 代码 debug / 讨论),AI 评分 + 给具体改进建议
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

---

## 版权边界

- **自动下载**:仅限作者主动公开的源(arxiv 预印本、GitHub 公开仓库)
- **不会做**:绕过付费墙抓闭源期刊 PDF、Sci-Hub 等灰色源
- **闭源资源**:Agent 给链接 + 你已合法获取的 PDF 可手动放进 `workspace/library/papers/`,Agent 可以基于它出题、答疑

---

## 接下来的版本(MVP 之后)

按周迭代:

- **Week 2**:Archivist Agent(自动整理对话/笔记成知识库)+ 多源 librarian(博客抓取、YouTube 字幕)
- **Week 3**:FastAPI Web UI(浏览器看板 + 交互)、APScheduler 定时任务(每周日复盘、3 天没动提醒)
- **Week 4**:Reviewer Agent(阶段复盘报告)、知识地图自动生成、导出整个学习成果

---

## 故障排查

**`ANTHROPIC_API_KEY not set`** — 检查 `.env` 文件是否在项目根目录、是否填了 key。

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
    ├── config.py         # 环境变量与工作区
    ├── models.py         # Pydantic 数据模型
    ├── store.py          # 文件持久化
    ├── llm.py            # Anthropic 封装
    ├── orchestrator.py   # 状态机
    ├── planner.py        # 路径规划 Agent
    ├── librarian.py      # 资源获取 Agent
    ├── tutor.py          # 答疑 Agent
    ├── examiner.py       # 评测 Agent
    └── practice.py       # 最佳实践 Agent
```
