# Bitable Agent Fabric

> 让飞书多维表格从**记录系统**变成**业务操作系统**。
> 每来一条业务任务，系统先判断场景，再从技能库里自动组装一支最合适的 Agent Team，去解决问题并把过程沉淀下来。

飞书 AI 产品创新赛参赛项目 · MVP

---

## 它解决什么

企业协作三个痛点：

1. **记录 ≠ 操作**：多维表格记下问题，但无法自动解决。
2. **固定流程 ≠ 灵活业务**：突发故障、非标销售、异常招聘都要重新写 workflow。
3. **单点 AI ≠ 系统协作**：单个助手只能问答，复杂任务需要多角色协同。

**Bitable Agent Fabric** 把飞书多维表格当成"中台"：
- 用户往 Cases 表丢一条任务
- 系统自动识别场景 → 从 Skill Catalog 抽相关技能 → 动态组建 Agent 团队 → 各 Agent 独立工作 → Verification Agent 独立验收 → 成功沉淀为 SOP
- **全过程** 在多维表格里可见：Cases 的 status 流转、Agent Runs 表逐条出现、成功后 Memory/SOP 新增一行

## 架构

```
┌───────────────────────────────────────────────┐
│  CLI (typer)   baf init / login / run-demo   │
├───────────────────────────────────────────────┤
│  Orchestrator  路由 → 编组 → 执行 → 验证 → 沉淀│
│  ┌──────────┬─────────────┬───────┬────────┐  │
│  │SceneRouter│SkillRetriever│Composer│ IC/RC/FX/VF│
│  └──────────┴─────────────┴───────┴────────┘  │
├───────────────────────────────────────────────┤
│  Storage 抽象   BitableBackend / MockBackend │
│  LLM Client (OpenAI 兼容 → zhizengzeng)        │
└───────────────────────────────────────────────┘
```

**关键设计**：所有 Agent 读写数据都走 `StorageBackend` 抽象。开发期用 `MockBackend`（本地 JSON，无需飞书凭证即可全流程演示），切到真飞书时零改动。

## 五张多维表格

| 表 | 作用 |
|---|---|
| **Cases** | 任务主表，每条业务问题一行 |
| **Skill Catalog** | 技能库，每个 skill 独立定义，可治理、可审计 |
| **Agent Blueprints** | Agent 团队模板，成功组合被保留以供复用 |
| **Agent Runs** | 每一次 Agent 调用的时间线（虚拟组织的工作可视化） |
| **Memory / SOP** | 成功处置沉淀为可复用 SOP |

## 7 个内置 Agent + Court

```
Scene Router       → 分类任务到 6 个场景            (concurrency-safe, low risk)
Skill Retriever    → 从技能库挑 5-10 个候选         (concurrency-safe, low risk)
Agent Composer     → 复用 Blueprint 或 LLM 设计新团队 (concurrency-safe, low risk)
Incident Commander → 故障分级 + 调度                (serial, mid risk)
Root Cause Agent   → 日志+监控 → 推根因             (concurrency-safe, mid risk)
Fix Agent          → 修复方案 + 回滚 + 审批卡片     (DESTRUCTIVE → approval)
Verification Agent → 独立验收（低风险快速通道）     (concurrency-safe, low risk)
Court Agent        → Verifier+Skeptic+Domain Expert (高风险 3 角色法庭)
```

每个 Agent 都带 `is_concurrency_safe / is_destructive / risk_tier / search_hint`
四个元数据，Composer 据此决定哪些 Agent 同 tick 并行、哪些必须走审批、
哪些要进 Court。这套元数据接口直接抄 Claude Code `src/Tool.ts`。

## Sprint A/B/C 进阶能力（DMSAS_Design.md 落地）

| 能力 | 实现位置 | 何时启用 |
|---|---|---|
| Async generator + tick 调度 | `orchestrator_stream.py` | `baf run-stream` |
| Resume from checkpoint | `StreamOrchestrator.run_case_stream` + `storage.get_max_tick` | `baf resume <CASE>` |
| 三角色法庭（Court） | `agents/court.py` | `risk_tier ∈ {high, critical}`，故障场景默认进 Court |
| 异步审批（飞书卡片） | `hooks/approvals.py` (`ApprovalRegistry`) | Fix Agent (`is_destructive=True`) 自动触发 |
| 经验自蒸馏（SOP + 新技能 + EWMA） | `evolution/distill.py` | Court 通过后自动 |
| AFlow-MCTS 多路径采样 | `evolution/aflow_mcts.py` | Composer 第三档（高风险时调用） |
| Skill Hub（向量召回 + MCP + 政策） | `skills/hub.py` | 任何 Agent 内显式 `hub.invoke(skill_id, args)` |

## 快速上手

### 1. 安装

```bash
git clone <this-repo>
cd bitable-agent-fabric
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # 填上 LLM_API_KEY
```

### 2. 离线 Demo（不需要飞书凭证）

```bash
baf init-tables --mock   # 在 ~/.baf/mock/ 下创建 6 张 JSON "表"
baf seed --mock          # 种入内置技能库（19 条）+ 模板（4 条，覆盖 4 个场景）
baf run-demo --mock      # 跑一条默认的 P1 故障，控制台实时输出每个 Agent 的工作
baf demo-all --mock      # 一次跑完 4 个场景：故障 / 销售 / 招聘 / 采购
baf tables --mock        # 一览 6 张表
baf stats --mock         # 场景 / 状态 / Blueprint 使用率聚合
baf trace <CASE_ID> --mock          # 单 case 的完整 Agent 时间线
baf export-report --mock -o out.md  # 导出 Markdown 报告（评委/分享友好）

# Sprint A/B/C 高阶通路：
baf run-stream "Redis 主节点宕机..." --mock   # async + Court + 自动审批
baf resume CASE_xxxxx --mock                  # 从最大 tick + 1 续跑
baf approve <card_id> --decision approved --mock  # 手动通过审批
baf court-test "数据库雪崩" --mock            # 单独跑三角色法庭
```

期望看到的控制台输出：

```
─── 新 Case CASE_xxxxx ───
title: 订单服务响应超时，疑似数据库连接池耗尽
Scene Router     {"scene_type":"故障处置","confidence":0.99,...}
Skill Retriever  {"picked":["SKILL_001","SKILL_002",...],"total_candidates":7}
Agent Composer   {"source":"blueprint","blueprint_id":"BP_INCIDENT_V1",...}
Incident Commander {"severity":"P1","need_oncall_notify":true,...}
Root Cause Agent {"root_cause":"数据库连接池耗尽...","confidence":0.85}
Fix Agent        {"steps":[...], "rollback":"...", "risk_overall":"中"}
Verification Agent {"passed":true,"score":0.95,"summary":"..."}
📌 SOP 已沉淀: SOP_故障处置_CASE_xxxxx
─── Case CASE_xxxxx → PASSED ───
```

### 3. 自定义一条 Case

```bash
baf run "Redis 主节点宕机，大量 connection refused，紧急修复" --mock
# 场景自动识别 → 故障处置；组建 IC+RC+FX+VF
baf run "客户王总今天朋友圈说要做数字化升级，给个跟进策略" --mock
# 场景自动识别 → 销售推进；Composer 会 LLM 生成新 team 并存为新 Blueprint
```

### 4. 真飞书路径

先去飞书开放平台创建一个自建应用：

1. 登录 https://open.feishu.cn → 开发者后台 → 创建应用
2. 能力：开通 **多维表格**、**身份验证 (Auth)**
3. 权限：`bitable:app`, `bitable:app:readonly`
4. 重定向 URL 里加 `http://127.0.0.1:18080/callback`
5. 拿到 `App ID` / `App Secret`
6. 在你要用的多维表格 URL 里复制 `/base/<app_token>` 的 `app_token`

然后：

```bash
baf init                 # 填 LLM key + Feishu app_id/secret/bitable_app_token
baf login                # 浏览器授权，拿 user_access_token
baf init-tables          # 飞书中自动创建 5 张表
baf seed                 # 把 10 条内置技能写入
baf run-demo             # 打开多维表格页面能看到 Cases/AgentRuns 实时新增行
```

### 5. 回归测试

```bash
pytest -q
# 17 passed, 1 skipped —— 完全离线（除 Scene Router 真 LLM 测试）
```

| 测试 | 校验内容 |
|---|---|
| `test_scene_router.py` | 20 fixture 场景识别准确率（PRD §10.1 要求 ≥85%，实测 100%）|
| `test_mock_backend.py` | StorageBackend CRUD、列表过滤（含多选字段）、seed 幂等 |
| `test_orchestrator_e2e.py` | FakeLLM 跑完整流水线，校验 Blueprint EWMA、SOP 沉淀、Agent Runs 审计 |
| `test_court_and_evolution.py` | Court 三角色多数表决 / 快速通道、Evolution 蒸馏、ApprovalRegistry round-trip、AflowMCTS 评分、SkillHub 检索 |
| `test_orchestrator_stream.py` | Async stream 全流水线（含审批与 Court）+ tick 续跑 |

## 目录

```
bitable-agent-fabric/
├── src/baf/
│   ├── cli.py                       # typer CLI（含 run-stream/resume/approve/court-test）
│   ├── config.py                    # ~/.baf/ 配置 & 凭证
│   ├── llm/client.py                # OpenAI-compatible 客户端
│   ├── bitable/
│   │   ├── auth.py                  # Feishu OAuth 浏览器流程
│   │   ├── client.py                # Bitable REST 封装
│   │   └── schemas.py               # 6 张表字段定义（PendingApprovals 新增）
│   ├── storage/
│   │   ├── backend.py               # StorageBackend 抽象（+ get_max_tick / vector_search）
│   │   ├── mock_backend.py          # 本地 JSON
│   │   └── bitable_backend.py       # 飞书
│   ├── agents/                      # Scene/Skill/Composer/IC/RC/Fix/Verification/Generic
│   │   ├── base.py                  # +元数据 (concurrency_safe / destructive / risk_tier / search_hint)
│   │   └── court.py                 # 三角色法庭：Verifier / Skeptic / DomainExpert
│   ├── skills/
│   │   ├── builtin.py               # 19 条种子技能 + 4 个 Blueprint
│   │   └── hub.py                   # Skill Hub：retrieve / invoke / 政策
│   ├── evolution/
│   │   ├── distill.py               # SOP + 自蒸馏新技能 + Blueprint EWMA
│   │   └── aflow_mcts.py            # AFlow MCTS 评分多路径采样
│   ├── hooks/approvals.py           # 异步审批 Hook（飞书卡片 + 超时）
│   ├── orchestrator.py              # 同步主流程（保持向后兼容）
│   ├── orchestrator_stream.py       # Async generator + tick + Court + 审批
│   └── demo/                        # Demo 数据 & 种子逻辑
├── tests/                           # 17 个用例（5 个测试文件）
│   ├── test_mock_backend.py
│   ├── test_scene_router.py         # 真 LLM 回归（自动 skip 当无 key）
│   ├── test_orchestrator_e2e.py     # 同步流水线
│   ├── test_orchestrator_stream.py  # 异步流水线 + 续跑
│   ├── test_court_and_evolution.py  # Court / Evolution / Approvals / SkillHub
│   └── fixtures/cases.jsonl         # 20 条样本
├── DMSAS_Design.md                  # 设计文档（论文锚点 + 工程模式 + 代码骨架）
├── architecture.png                 # 架构图
├── pyproject.toml
└── .env.example
```

## 设计亮点（为什么值得评委看）

- **动态编组** — Composer 不是写死 5 个 Agent，而是先查 Blueprints，找不到才让 LLM 现设计，成功后持久化
- **技能驱动** — 所有能力都在 Skill Catalog 表里，有权限、风险、验收标准字段，可治理、可扩展
- **全链路审计** — 每个 Agent 的每次调用都在 Agent Runs 表留痕，评委能直接在多维表格里看到"虚拟组织的工作时间线"
- **自沉淀** — 验证通过的 case 自动写入 Memory/SOP 表，下次同类问题 Composer 会优先复用
- **自演化** — Blueprint 的 `success_rate` 用 EWMA(α=0.3) 在每次 case 关闭后滚动更新，"好用的模板"越用越靠前
- **跨场景复用** — 同一套底座，4 个场景都预置了 Blueprint；新场景只需补技能数据零改代码（`baf run "<销售/招聘/采购 任意描述>"` 就能工作）
- **可视化报告** — `baf trace`/`stats`/`export-report` 三个命令分别给单 case / 聚合 / Markdown 导出三种角度
- **离线可跑** — MockBackend + 端到端 FakeLLM 测试，保证评委和 CI 在无任何外部依赖时也能验证

## 已知限制 / 下一步

- 多模态输入（截图 OCR、语音 ASR）工具已预留接口，MVP 只接文本
- Fix Agent 的飞书卡片审批当前走 mock，V1.1 要接入真的 `send_feishu_card`
- Root Cause 的 `read_logs` / `query_monitoring` 是固定样例，企业对接时替换为真实 APM/日志 SDK
- 当前 Agent 串行执行，V1.1 把不依赖结果的 Agent 并行化（e.g. 复杂销售场景里 Research / Risk / Proposal 可以并发）
- Blueprint 当前 4 个（故障/销售/招聘/采购），运营分析等场景走 LLM 首次设计后自沉淀

---

**"让飞书多维表格从记录系统，变成了一个会按场景自动生成虚拟组织的业务操作系统。"**
