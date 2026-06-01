# RL Agent Tutor — 产品需求文档（PRD）

| 字段 | 值 |
|------|-----|
| 文档版本 | v0.3.0 |
| 对应代码版本 | commit `82e3bf1` |
| 最后更新 | 2026-05-25 |
| 状态 | Active |
| 关联文档 | [TECH-DESIGN.md](./TECH-DESIGN.md) · [architecture.md](./architecture.md) |

---

## 1. 背景与动机

### 1.1 问题陈述

工业界与学术界把 RL / LLM post-training（RLHF、DPO、GRPO、PPO、Reward Modeling 等）作为大模型时代的核心工程能力，但学习者面临三个真实痛点：

1. **资料碎片化** —— arxiv 论文、GitHub 实现、博客解读、YouTube 讲座散落各处，没有统一入口；
2. **学习路径不可执行** —— 教程多是"告诉你看什么"，少有"逼你产出什么"，学完仍然写不出代码；
3. **AI 助手是被动工具** —— ChatGPT / Claude 答得了问题，但不知道你"在哪一步"、"上一题做错了什么"、"下一步该干啥"。

### 1.2 产品愿景

> **不是答你问题的聊天机器人，是带你完成学习闭环的私人教练。**

把 LLM 当作执行器，把状态机和文件系统当作大脑，让 Agent 主动驱动「规划 → 取资源 → 答疑 → 自测 → 反馈 → 推进」的整个学习周期。

---

## 2. 目标用户与场景

### 2.1 主要用户画像

| 画像 | 描述 | 核心诉求 |
|------|------|---------|
| **算法工程师转型 RLHF** | 有 PyTorch / 监督学习经验，零 RL 基础 | "我要在 4 周内能用 TRL 跑通 RLHF" |
| **博士在读做 alignment** | 论文读得多但未落地 | "把 PPO/DPO/GRPO 真正吃透并能复现" |
| **资深工程师补 AI 短板** | 有十年系统经验，AI 是新坑 | "用工程化的方式系统学，不要碎片输入" |

**共同特征**：
- 自驱型学习者，但需要外力维持节奏
- 重视隐私（不愿对话被云服务采集）
- 偏好命令行 / 本地工具

### 2.2 核心使用场景

- **场景 A · 周末规划**：周日晚定下未来 4 周目标，让 Agent 出可执行学习计划。
- **场景 B · 工作日深度学习**：工作日抽 1-2 小时，跟当前节点交互（fetch / ask / test）。
- **场景 C · 异步复盘**：周日 18:00 自动生成周复盘，周一 08:00 推送本周焦点。
- **场景 D · 多目标并行**：白天的工作研究、晚上的兴趣项目用不同 workspace 隔离。

### 2.3 反向用户（不为谁设计）

- ❌ 想要"五分钟速通 PPO"的速成派 —— 本工具的设计哲学是深度优于广度。
- ❌ 团队协作场景 —— 单用户单机，无权限模型、无多人编辑。
- ❌ 通用问答工具 —— 离开了节点上下文，Tutor 没有特别优势。

---

## 3. 核心价值主张

| 核心价值 | 现状（市面方案） | 本产品 |
|---------|----------------|--------|
| **主动驱动** | ChatGPT 被动应答 | 状态机 + Daemon 主动推进 |
| **资源闭环** | 散落多处 | arxiv/GitHub/blog/YouTube 一键到本地 |
| **可验证学习** | "学完就忘" | 每节点 5 题自测 + 评分 + 反馈 |
| **隐私本地** | 云端记录全过程 | 全部 JSON / Markdown 落本地，可 git |
| **多角色协作** | 单 prompt 包打天下 | 9 个专职 Agent，各司其职 |

---

## 4. 功能需求（FR）

> 优先级：**P0 = MVP 必须**；**P1 = 当前版本已交付**；**P2 = 路线图**

### 4.1 学习计划（Planning）

| ID | 需求 | 优先级 | 验收 |
|---|------|--------|------|
| FR-PLAN-1 | 用户给目标 + 当前水平，Agent 产出 4-6 阶段、每阶段 3-5 节点的结构化计划 | P0 | `rl-agent plan "<goal>"` 后 `plan.json` 存在且合法 |
| FR-PLAN-2 | 每个节点必须有可验证的产出（代码 / 笔记 / 曲线 / 书面解释） | P0 | objectives 字段非空，且不是「理解 X」式描述 |
| FR-PLAN-3 | 节点估时基于 10-15 小时/周的 part-time 投入 | P0 | estimated_hours 是 (min, max) 元组 |
| FR-PLAN-4 | 已有计划时覆盖前需用户确认 | P0 | `rl-agent plan` 检测旧计划时弹 confirm |
| FR-PLAN-5 | 支持中途跳转节点（`goto`）和强制推进（`advance`） | P0 | 节点状态依据流转 |

### 4.2 资源获取（Resource Fetching）

| ID | 需求 | 优先级 | 验收 |
|---|------|--------|------|
| FR-FETCH-1 | 自动从 arxiv 搜并下载 PDF 到 `library/papers/` | P0 | `rl-agent fetch` 后 PDF 落盘且 `resources.jsonl` 有记录 |
| FR-FETCH-2 | 自动 `git clone --depth 1` GitHub 仓库到 `library/code/` | P0 | clone 失败要降级为「记录链接但不阻断」 |
| FR-FETCH-3 | 单条 URL 抓博客正文为 Markdown | P1 | `rl-agent fetch-blog <url>` |
| FR-FETCH-4 | YouTube 视频字幕扒为 Markdown（按 en/zh 优先级降级） | P1 | `rl-agent fetch-youtube <url\|id>` |
| FR-FETCH-5 | 已存在的 PDF / 已 clone 的仓库不重复抓 | P0 | 幂等检查 |
| FR-FETCH-6 | **不**绕过付费墙、Sci-Hub 等灰色源 | P0（合规） | 仅用 arxiv API 和 GitHub 公开仓 |

### 4.3 答疑（Tutoring）

| ID | 需求 | 优先级 | 验收 |
|---|------|--------|------|
| FR-ASK-1 | 回答时强制带入当前节点上下文（id / name / objectives） | P0 | system prompt 模板已注入 |
| FR-ASK-2 | 回答时拉取该节点最近 N 轮历史 Q&A | P0 | 多轮对话连贯 |
| FR-ASK-3 | 检测到本地有 PDF 索引时自动 RAG，强制引用 `[doc_id · §sec · p.N]` | P1 | 引用格式校验 |
| FR-ASK-4 | 风格约束：直接、不寒暄、技术术语保留英文 | P0 | system prompt 已写死 |

### 4.4 自测（Self-Testing）

| ID | 需求 | 优先级 | 验收 |
|---|------|--------|------|
| FR-TEST-1 | 每节点出 5 题，覆盖 4 种类型（concept / derivation / code-debug / discussion） | P0 | exercises.jsonl 题型分布正确 |
| FR-TEST-2 | 用 RAG 把题目 ground 在本地材料上（至少 2 题） | P1 | 题目里出现具体片段 |
| FR-TEST-3 | 单题评分 0-1 + 结构化反馈（✅ ⚠️ ❌ 👉） | P0 | feedback 含四段标记 |
| FR-TEST-4 | avg ≥ 0.8 自动建议 `advance`，< 0.8 建议回炉 | P0 | state 流转正确 |
| FR-TEST-5 | 学习活动全留痕到 `trajectory.jsonl` | P0 | 每次 ask/test/fetch 都有记录 |

### 4.5 行业实践（Best Practices）

| ID | 需求 | 优先级 | 验收 |
|---|------|--------|------|
| FR-PRAC-1 | 给当前节点话题，输出 must-do / common mistakes / preferred tools / from-the-trenches | P0 | 4 个固定 section |
| FR-PRAC-2 | 风格：来自一线工程师视角，给具体超参 / 库选型 | P0 | system prompt 强约束 |

### 4.6 知识库与复盘

| ID | 需求 | 优先级 | 验收 |
|---|------|--------|------|
| FR-KB-1 | 把节点的对话+练习+资源蒸馏成 Markdown KB 条目 | P1 | `rl-agent archive` 产出 `notes/<id>_<slug>.md` |
| FR-KB-2 | 顶层 KB 索引（`INDEX.md`）按 stage 分组 | P1 | `rl-agent archive` 后自动重建 |
| FR-KB-3 | 周复盘：聚合最近 7 天活动 → Markdown 报告 | P1 | `rl-agent review-weekly` |
| FR-KB-4 | 阶段复盘：所有节点完成后产出知识地图（mermaid） | P1 | `rl-agent review-stage <id>` |

### 4.7 主动驱动（Daemon）

| ID | 需求 | 优先级 | 验收 |
|---|------|--------|------|
| FR-DAEMON-1 | 每周日 18:00 自动生成周复盘 | P1 | APScheduler cron 触发 |
| FR-DAEMON-2 | 每天 09:00 检测闲置 ≥ N 天，写 nudge + 系统通知 | P1 | macOS osascript / Linux notify-send |
| FR-DAEMON-3 | 每周一 08:00 刷新当前节点 KB + 推「本周焦点」 | P1 | 通知出现 |

### 4.8 多工作区（Workspaces）

| ID | 需求 | 优先级 | 验收 |
|---|------|--------|------|
| FR-WS-1 | 支持创建 / 切换 / 重命名 / 删除工作区 | P1 | `rl-agent workspace <subcmd>` |
| FR-WS-2 | 每个工作区独立的 `library/` + `progress/` | P1 | 切换后数据隔离 |
| FR-WS-3 | 旧 `./workspace/` 自动迁移为 `default` | P1 | `migrate_legacy()` 幂等 |

### 4.9 交付形态（Delivery）

| ID | 需求 | 优先级 | 验收 |
|---|------|--------|------|
| FR-CLI-1 | typer + rich 美化输出，28 个命令覆盖完整流程 | P0 | `rl-agent --help` 全列出 |
| FR-WEB-1 | FastAPI + 单页内嵌 HTML，浏览器看板交互 | P1 | `rl-agent serve` 后 8765 可访问 |
| FR-DEPLOY-1 | 一键脚本支持 macOS launchd / Linux systemd user / Docker Compose | P1 | `bash deploy/install-native.sh` |

---

## 5. 非功能需求（NFR）

| 维度 | 要求 |
|------|------|
| **隐私** | 100% 本地数据，除 LLM 调用外不出网（资源抓取除外） |
| **可移植** | 全 JSON / JSONL / Markdown，纯文本可 git 跟踪、可手改 |
| **韧性** | LLM 有 3 次指数退避；JSON 解析有 3 段救援；外部抓取失败要降级而非阻断 |
| **可解释** | `trajectory.jsonl` 留全痕，可审计每一次 Agent 调用 |
| **语言** | 输出强制中文（系统提示词写死），技术术语保留英文 |
| **响应速度** | 单次 `ask` ≤ 30 秒（LLM 决定上限），`fetch` ≤ 3 分钟 |
| **依赖** | Python 3.11+，开箱即用，无需 Docker |
| **合规** | 不抓付费墙、不绕版权 |

---

## 6. 范围边界（In/Out of Scope）

### 6.1 In Scope

- ✅ 单用户、单机、本地数据
- ✅ Anthropic / OpenRouter 两个 LLM provider
- ✅ arxiv / GitHub / blog / YouTube 四类资源源
- ✅ CLI + Web UI + Daemon 三种交付
- ✅ macOS / Linux 部署

### 6.2 Out of Scope

- ❌ 团队协作（多人共享、权限）
- ❌ 移动端原生 App（用 Tailscale + Web UI 替代）
- ❌ 收费版 / 云端托管
- ❌ Windows 原生（仅通过 WSL 间接支持）
- ❌ 视频内容理解（仅扒字幕，不做视觉）
- ❌ 教练式催更（除 nudge 外不做主动消息推送）

---

## 7. 成功指标（Metrics）

> 由于是单用户工具，指标定义为「在我自己使用过程中的可观察数据」。

| 指标 | 目标 |
|------|------|
| 计划完成率 | 60% 节点能走到 completed（不是放弃） |
| 平均自测分 | 全计划 avg ≥ 0.7 |
| 资源利用率 | 每节点至少 1 个 RAG 命中（说明抓的资源在用） |
| 闲置中断率 | nudge 触发 ≤ 2 次/月（说明节奏稳定） |
| LLM 失败率 | < 1%（重试后） |

---

## 8. 路线图（Roadmap）

### 8.1 已交付（v0.3.0）
- 9 个 Agent 完整闭环
- RAG 子系统
- 多工作区
- Web UI / Daemon
- 三种部署方案

### 8.2 短期（v0.4，1-2 个月内）
- **Reviewer 自动触发**：阶段所有节点完成时自动出 stage review
- **Telemetry**：本地指标看板（学习时长 / 准确率分布 / 资源利用率）
- **导出**：把整个学习成果导出为单文件 PDF / EPUB

### 8.3 中期（v1.0，半年内）
- **多模态 RAG**：图表 / 公式截图引入索引
- **代码沙箱**：code-debug 题目可在隔离环境跑测
- **知识地图**：跨阶段自动生成 mermaid 知识图谱

### 8.4 长期（探索）
- 团队版（多人共享 KB，节点 fork/PR 模式）
- 细分赛道（不仅限 RL/LLM，扩展到 systems / distributed / formal methods）

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM 提供方涨价 / 停服 | 工具不可用 | 双 provider 设计（Anthropic + OpenRouter），任一可工作 |
| arxiv / YouTube 改 API | fetch 部分失效 | Librarian 单源失败不阻断，记录链接降级 |
| 用户流失（学不下去） | 工具无价值 | Daemon 闲置 nudge + 周复盘维持节奏 |
| 数据丢失 | 历史轨迹消失 | 全本地文件，鼓励 `git init workspace/` |
| LLM 出错给错答案 | 学习被误导 | RAG 强制引用 + 鼓励用户做 self-test 验证 |

---

## 10. 公开承诺与版权

- **自动下载**：仅限作者主动公开的源（arxiv 预印本、GitHub 公开仓）。
- **不会做**：绕过付费墙、Sci-Hub 等灰色源。
- **闭源资源**：Agent 给链接 + 用户已合法获取的 PDF 可手动放进 `library/papers/`，Agent 可基于它出题、答疑。

---

_本 PRD 是「代码反推」的产物，记录的是已实现的产品形态，而非空想。后续修改请保持「PRD ↔ 代码」的一致性。_
