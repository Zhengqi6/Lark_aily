# Bitable Agent Fabric · 运行指南

完整的运行步骤（从零到跑通 demo）和命令清单。所有命令都在仓库根目录执行。

---

## 0. 环境准备（一次性）

要求：Python ≥ 3.10、`pip`、Git。

```bash
# 1. 克隆并进入仓库
cd /path/to/Lark_aily

# 2. 创建并激活虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. 安装本项目（editable 模式 + 开发依赖）
pip install -e .
pip install pytest pytest-asyncio   # 如需跑测试

# 4. 配置 LLM key（仅需一次）
cp .env.example .env                # 然后编辑 .env，填入 LLM_API_KEY
# 或者：
export LLM_API_KEY="sk-..."
export LLM_BASE_URL="https://api.zhizengzeng.com/v1/"
export LLM_MODEL="gpt-4o-mini"
```

> **不想配 LLM？** 测试套件全部带 FakeLLM，运行 `pytest -q` 不需要任何外部依赖。

---

## 1. 完全离线 Demo（无飞书凭证、无 LLM key）

只想看代码逻辑跑通：直接 `pytest -q`，所有 17 个用例都用 FakeLLM 离线运行：

```bash
pytest -q
# 预期输出: 17 passed, 1 skipped (Scene Router 真 LLM 测试自动跳过)
```

---

## 2. Mock 后端 Demo（本地 JSON 模拟飞书表）

适合演示给评委/同事看完整工作流，但不想/不能配飞书。

```bash
# Step 1 — 创建 6 张本地 JSON "表"  (~/.baf/mock/*.json)
baf init-tables --mock

# Step 2 — 种入 19 条内置技能 + 4 个 Blueprint（覆盖 4 个场景）
baf seed --mock

# Step 3 — 跑一条 P1 故障 case，控制台实时输出每个 Agent 的工作
baf run-demo --mock

# Step 4 — 跨场景批量演示（故障 + 销售 + 招聘 + 采购）
baf demo-all --mock

# Step 5 — 看一眼 6 张表（Cases / SkillCatalog / AgentBlueprints /
# AgentRuns / MemorySOP / PendingApprovals）
baf tables --mock

# Step 6 — 单 case 时间线（虚拟组织的工作可视化）
baf trace CASE_xxxxx --mock

# Step 7 — 聚合统计（场景 / 状态 / Blueprint 使用率 / SOP 数）
baf stats --mock

# Step 8 — 导出 Markdown 报告（评委/分享友好）
baf export-report --mock -o report.md
```

控制台输出示例：

```
─── 新 Case CASE_3a8f1b6c2e ───
title: 订单服务响应超时，疑似数据库连接池耗尽
Scene Router     {"scene_type":"故障处置","confidence":0.99,...}
Skill Retriever  {"picked":["SKILL_001","SKILL_002",...],"total_candidates":7}
Agent Composer   {"source":"blueprint","blueprint_id":"BP_INCIDENT_V1",...}
Incident Commander {"severity":"P1","need_oncall_notify":true,...}
Root Cause Agent {"root_cause":"数据库连接池耗尽...","confidence":0.85}
Fix Agent        {"steps":[...], "rollback":"...", "risk_overall":"中"}
Verification Agent {"passed":true,"score":0.95,"summary":"..."}
📌 SOP 已沉淀: SOP_故障处置_CASE_3a8f1b6c
─── Case CASE_3a8f1b6c2e → PASSED ───
```

---

## 3. Sprint A/B/C 高阶通路（异步流 + 法庭 + 审批 + 演化）

完整的 DMSAS 设计落地，每一步事件流都打到控制台。

```bash
# 异步管道：Scene → Skill+Composer → 并行 tick → Court → Evolution
baf run-stream "Redis 主节点宕机，大量 connection refused，紧急修复" --mock
```

输出形态（节选）：

```
<perception>          tick=1   {"scene_type":"故障处置",...}
<skills>              tick=2   {"picked":[...]}
<composed>            tick=3   {"source":"blueprint",...}
<tick_done>           tick=4   {"tick":4,"roles":["incident_commander"]}
<tick_done>           tick=5   {"tick":5,"roles":["root_cause"]}
<approval_requested>  tick=6   {"role":"fix","card_id":"card_a1b2c3..."}
✓ auto-approved card_a1b2c3 (demo)
<approval_resolved>   tick=6   {"status":"approved",...}
<court>               tick=7   {"passed":true,"score":0.91,"votes":[3 personas]...}
<memorized>           tick=8   {"sop_id":"SOP_故障处置_xxx",
                                "new_skills":["SKILL_AUTO_root_cau_xxx"]}
<done>                tick=8   {"passed":true,...}
```

### 续跑（resume from checkpoint）

任务中途崩溃 / 网络断开 / 进程被杀，下次直接续跑：

```bash
baf resume CASE_xxxxx --mock
# 自动从 storage.get_max_tick(case_id) + 1 开始，rehydrate 出 ctx.findings 继续。
```

### 手动审批（生产模式）

`run-stream` 默认 demo 自动通过审批。生产关掉 auto-approve 后：

```bash
baf approve <card_id> --decision approved --note "已和值班同学确认" --mock
# 或：
baf approve <card_id> --decision rejected --note "回滚条件不充分" --mock
```

### Court 单测（高风险三角色法庭）

```bash
baf court-test "数据库雪崩导致全国订单失败" --mock
# 输出 3 个 persona（Verifier/Skeptic/SRE-Expert）的独立打分 + 多数决裁定。
```

---

## 4. 真飞书路径（生产模式）

把 MockBackend 切换到 BitableBackend，所有数据落地到真飞书多维表格。

### 4.1 飞书开放平台准备

1. 登录 https://open.feishu.cn → 开发者后台 → 创建自建应用
2. 启用能力：**多维表格** + **身份验证 (Auth)**
3. 添加权限：`bitable:app`, `bitable:app:readonly`
4. 重定向 URL 加 `http://127.0.0.1:18080/callback`
5. 拿到 `App ID` / `App Secret`
6. 创建一个多维表格，URL 形如 `https://feishu.cn/base/<APP_TOKEN>?...`，复制 `<APP_TOKEN>`

### 4.2 配置 + 登录

```bash
baf init             # 交互式填入 LLM key + Feishu app_id/secret/app_token
baf login            # 浏览器打开授权页，授权完拿到 user_access_token
baf init-tables      # 自动创建 6 张表
baf seed             # 写入 19 条内置技能 + 4 个 Blueprint
```

### 4.3 跑业务

完全等同 mock 模式，只是去掉 `--mock`：

```bash
baf run-demo
baf demo-all
baf run-stream "..."
baf trace CASE_xxxx
baf export-report -o report.md
```

执行过程在飞书多维表格里 **实时可见**：
* `Cases · 任务` 行的 `status` 字段会从 `识别中` 一路流转到 `已完成`
* `Agent Runs · 执行记录` 每秒新增一行（甘特图视图直接看时间线）
* 通过的 case 在 `Memory/SOP · 沉淀` 表多一条 SOP
* Fix 等危险 Agent 触发的审批写到 `Pending Approvals · 待审批`

---

## 5. 测试

```bash
# 全量
pytest -q

# 只跑某个文件
pytest tests/test_orchestrator_stream.py -v

# 跑 Scene Router 真 LLM 回归（PRD 要求 ≥85%，实测 100%）
LLM_API_KEY=sk-... pytest tests/test_scene_router.py -v
```

---

## 6. 常用故障排查

| 症状 | 原因 / 解决 |
|---|---|
| `ERROR: Package 'bitable-agent-fabric' requires Python ≥ 3.10` | 升级 Python，或用 `python3.11 -m venv .venv` |
| `LLM_API_KEY 未配置` | `cp .env.example .env` 后填入 key，或 `export LLM_API_KEY=...` |
| `feishu_bitable_app_token 未配置` | 跑 `baf init` 填入，或加 `--mock` 走离线 |
| `OAuth timeout (180s)` | 重定向 URL 没加 `/callback`，或浏览器没访问到 127.0.0.1:18080 |
| 真飞书写入报 `1254045` (单选项不存在) | 字段定义里枚举值飞书自动添加，重试一次即可；schemas.py 已带最常见枚举 |
| Mock JSON 文件残留旧数据 | 直接 `rm -rf ~/.baf/mock/`（或 `BAF_HOME=/tmp/.baf-test` 隔离） |

---

## 7. 一句话回放

```bash
# 完整 e2e
pip install -e . && baf init-tables --mock && baf seed --mock && baf demo-all --mock && pytest -q
```

输出末尾的总览表会告诉你 4 个场景全部 ✓ 通过、17 个测试全部 PASSED。

---

**"让飞书多维表格从记录系统，变成了一个会按场景自动生成虚拟组织的业务操作系统。"**
