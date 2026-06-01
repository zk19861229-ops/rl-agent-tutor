# 集成测试与验收

## 单元测试 (无 LLM, 无网络, 秒级)

跑纯逻辑层测试，验证 slugify / 原子写 / repo 校验 / SSRF 拦截 /
状态机归一化 / mtime 缓存等边界:

```bash
cd rl-agent-tutor
python tests/test_units.py
```

零 API 成本，约 1 秒。CI 应当跑这个，smoke_test 留给手工验证。

## 自动冒烟测试

跑一遍完整链路,任何一个 Agent 断了都会立刻在哪个 step 报错:

```bash
cd rl-agent-tutor
python tests/smoke_test.py
```

参数:
- `--quick` — 跳过 librarian/indexer/RAG 三步(没网或想省 API 时用)
- `--verbose` — 失败时打完整 traceback

测试用独立的 `./workspace_smoketest/` 目录,**不会污染你真实的 workspace**。

跑完大约 3-5 分钟,API 成本 $0.5-1.5(完整 RAG 链路约 30 次 LLM 调用)。

### 测试覆盖的 14 个 step

| # | Step | 验证什么 |
|---|---|---|
| 1 | import all modules | 所有 Python 文件无语法错 |
| 2 | LLM smoke call | API key、provider 路由通了,模型返回正常 |
| 3 | planner.make_plan | 能产出至少 1 阶段 + 1 节点的结构化计划 |
| 4 | orchestrator | 状态机能给出 next action 建议 |
| 5 | tutor.ask (no rag) | 无索引时 tutor 仍能答,citations 为空 |
| 6 | examiner | 能出 5 道题、能给弱答案打低分 |
| 7 | practice | 行业实践输出有内容(>200 字) |
| 8 | librarian.fetch_for_node | arxiv 下 PDF / GitHub clone / 博客抓取至少有 1 条成功 |
| 9 | indexer.index_papers | 步骤 8 下载的 PDF 能被解析切分 |
| 10 | rag.retrieve | BM25 召回有结果 |
| 11 | tutor.ask (with rag) | 有索引时 tutor 返回带 citations |
| 12 | archivist | 能从 trajectory 写出 KB Markdown |
| 13 | reviewer | 能生成周复盘 Markdown |
| 14 | persistence | 重新 load 数据完整保留 |

## Web UI 手工验收清单

脚本验证不了视觉/交互层。`rl-agent serve` 后,在浏览器里逐项确认:

- [ ] 首屏显示 metaLine(provider · 状态)
- [ ] 学习路径树左侧渲染,点节点能切换 current
- [ ] 当前节点右侧 5 个动作按钮全部可点
- [ ] 抓资源后,资源 tab 列表显示本地路径
- [ ] 提问后:答案渲染 markdown,**下方出现引用 chip**(如果索引有内容)
- [ ] 自测:5 题逐题作答,反馈颜色按分段显示(绿/黄/红)
- [ ] 自测全部结束自动归档(检查 exercises.jsonl 多了一条)
- [ ] 看板 tab:连续天数/完成节点/53 周热力图渲染正常
- [ ] RAG tab:重建索引按钮工作,检索框返回带 score 和章节信息的卡片
- [ ] 复盘 tab:点击生成周复盘,markdown 渲染完整

## 调度器手工验证

```bash
# 单独触发各 job 看效果(不用真等到周日)
python -c "from rl_agent_tutor.scheduler import job_weekly_review; job_weekly_review()"
python -c "from rl_agent_tutor.scheduler import job_idle_nudge; job_idle_nudge(idle_days=0)"
python -c "from rl_agent_tutor.scheduler import job_monday_focus; job_monday_focus()"
```

每个都会写一个文件到 `library/notes/{reviews,nudges}/`,Mac/Linux 还会弹桌面通知。

## 常见失败排查

**Step 2 失败,LLM 401/403** — `.env` 没找到或 key 错。`echo $ANTHROPIC_API_KEY` 检查环境。

**Step 8 失败** — 网络问题,或 arxiv 限流。重试一次通常就好。或者用 `--quick` 跳过看其他步骤是否健康。

**Step 9 报 "pymupdf not installed"** — `pip install -e .` 没装新依赖。重装。

**Step 12 失败,JSON 解析错** — LLM 偶尔不守规矩输出非 JSON。重跑通常能过;持续失败建议在 `.env` 切换到 `claude-opus-4-5` 或 `anthropic/claude-opus-4.5`。

**Step 13 失败,empty review** — 通常是 trajectory 太短(刚跑 smoke 没几条),正常使用一周后这步稳定。
