# RL Agent Tutor — 重构收尾说明

## 目标

本轮重构把产品从“功能集合”推进为“学习闭环教练”:

```text
配置资源源 → 获取核心资源 → 生成结构化课件 → 学习/提问 → 自测 → 证据链更新 → 推荐下一步 → 能力看板
```

## 已交付能力

### 1. 可配置资源源

新增 `sources/` 模块,默认支持:

- arxiv
- GitHub
- YouTube
- Web articles
- Local library

每个工作区可通过 `config/sources.yaml` 增加自定义源。当前版本会把 source 配置注入资源推荐提示,并把结果标记为 `source_id` 和 `priority`。

### 2. 资源证据链

`Resource` 新增:

- `source_id`
- `priority`
- `status`
- `used_by`

资源状态会随关键动作推进:

| 动作 | 资源状态 |
|---|---|
| 抓取 | `fetched` |
| 生成课件 | `read` |
| Tutor 使用 citation | `cited` |
| 自测提交 | `tested` |
| 归档知识库 | `archived` |

### 3. 结构化课件

新增 `courseware_schema.py`,支持:

- `Courseware`
- `CoursewareSection`
- `ContentBlock`
- `CoursewareReference`

课件生成优先产出 JSON,同时保留 Markdown:

```text
library/notes/courseware/<node>_<slug>.json
library/notes/courseware/<node>_<slug>.md
```

支持的 block:

- paragraph
- callout
- formula
- code
- table
- diagram
- image
- video
- quiz
- reference

### 4. 图文和视频样式

Web UI 已支持结构化课件渲染:

- 表格卡
- 公式卡
- 代码块
- 图解卡
- YouTube 视频卡
- 视频片段清单
- 检查点问题

Mermaid 目前以图解代码卡展示,尚未引入前端 Mermaid 渲染器。

### 5. 今日任务

新增 `services/workflow.py`,输出唯一推荐动作:

- `fetch_resources`
- `generate_courseware`
- `start_test`
- `remediate`
- `advance`
- `review`

`/api/plan` 返回 `recommended_action`,Web 学习页顶部显示“今日任务”卡。

### 6. 能力看板

新增 `services/dashboard.py`,在 `/api/stats` 的 `dashboard` 字段中返回:

- 平均自测分
- 掌握节点数
- 薄弱/未知节点数
- 资源利用率
- 估时进度
- 薄弱节点列表
- 当前推荐动作

## 新增测试

新增单元测试:

- `tests/unit/test_sources.py`
- `tests/unit/test_evidence.py`
- `tests/unit/test_courseware.py`
- `tests/unit/test_workflow.py`
- `tests/unit/test_dashboard_service.py`
- `tests/unit/test_static_build.py`

新增 API 级能力链路回归:

- `tests/api/test_capability_regression.py`

该测试不调用真实 LLM/网络,覆盖:

```text
sources.yaml → /api/sources → /api/plan 推荐动作
→ /api/courseware 结构化课件
→ Resource evidence read
→ /api/test/submit
→ /api/plan 推荐 advance
→ /api/stats 能力看板
```

## 验证命令

```bash
python scripts/build_static.py
python -m compileall -q src/rl_agent_tutor tests
pytest -q
python tests/test_units.py
node --check src/rl_agent_tutor/web/app.js
```

Vercel 兼容性 smoke:

```bash
VERCEL=1 python - <<'PY'
from fastapi.testclient import TestClient
from rl_agent_tutor.server import app
client = TestClient(app)
print(client.get('/api/health').status_code)
print(client.get('/api/stats').status_code)
PY
```

## 当前边界

- 自定义 source 目前参与配置、提示和结果标记;后续还需要把 RSS、local directory、GitHub allowlist 等拆成真正独立 provider。
- Mermaid 暂以代码卡展示,未渲染成 SVG/Canvas。
- 能力看板使用简单可解释规则,尚未做多维能力诊断。
- Vercel 仍适合作为 demo 部署;完整本地文件/RAG/daemon 能力更适合 Local Full Mode。
- `src/rl_agent_tutor/static/index.html` 是由 `scripts/build_static.py` 从 `web/` 生成的兼容产物,不要手工编辑。
