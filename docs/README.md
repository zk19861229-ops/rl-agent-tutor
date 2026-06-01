# 文档索引

`rl-agent-tutor` 项目的所有设计文档。三份文档相互交叉引用，按你的目的选择：

| 你想… | 看哪份 |
|-------|--------|
| 理解产品定位、用户场景、为什么做 | [PRD.md](./PRD.md) |
| 理解技术实现、模块边界、设计权衡 | [TECH-DESIGN.md](./TECH-DESIGN.md) |
| 一眼看懂系统怎么搭、各模块怎么协作 | [architecture.md](./architecture.md) |

---

## 文档清单

### 📋 [PRD.md](./PRD.md) — 产品需求文档
> 背景与动机 / 用户画像 / 核心价值 / 功能需求（FR）/ 非功能需求（NFR）/ 范围边界 / 成功指标 / 路线图 / 风险

### 🛠️ [TECH-DESIGN.md](./TECH-DESIGN.md) — 技术设计文档
> 设计原则 / 模块拆分 / 数据模型 / 关键流程 / 接口契约（CLI · HTTP · Agent）/ RAG 设计 / LLM 容错 / 存储 / 部署 / 设计权衡 / 已知限制

### 📐 [architecture.md](./architecture.md) — 架构图
> 5 张 mermaid 图：分层架构 / Agent 时序协作 / 状态机 / 数据流 / RAG 管线

---

## 文档维护规则

1. **代码反推优先于空想**：所有文档基于真实代码，不写「未来打算」之外的 vapor。
2. **三份文档必须一致**：FR-X 在 PRD 里描述需求，TECH-DESIGN 里描述实现，architecture 里画位置。
3. **commit 改代码时同步改文档**：行为变化 → PRD/TECH-DESIGN；模块变化 → architecture。
4. **版本号同步**：三份文档的 header 都标注「对应代码版本 = commit `xxxxxxx`」。

---

## 当前版本

| 文档版本 | v0.3.0 |
| 对应代码 | commit `82e3bf1` |
| 最后更新 | 2026-05-25 |
