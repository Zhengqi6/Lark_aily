# Bitable Agent Fabric — 运行报告

backend: `mock`  ·  cases: **5**  ·  agent runs: **35**  ·  SOP: **2**

## 概览

| 场景 | 数量 |
|---|---:|
| 故障处置 | 2 |
| 销售推进 | 1 |
| 招聘流程 | 1 |
| 采购审批 | 1 |

| 状态 | 数量 |
|---|---:|
| 已失败 | 3 |
| 已完成 | 2 |

## Case `CASE_d94450ef6c` — 订单服务响应超时，疑似数据库连接池耗尽
- scene: **故障处置**, severity: P1
- status: **已完成**
- summary: 任务完成，所有验收标准均满足。

### Agent timeline
| # | Agent | Status | Latency(ms) | Output |
|---:|---|---|---:|---|
| 1 | Scene Router | ok | 4518 | {"scene_type": "故障处置", "confidence": 0.99, "reasoning": "CPU持续高负载、接口响应时间飙升、下单失败", "need_confirmation": false} |
| 2 | Skill Retriever | ok | 1677 | {"picked": ["SKILL_001", "SKILL_002", "SKILL_003", "SKILL_004", "SKILL_007"], "total_candidates": 7, "reasoning": "根因分析和修复方案设计是解决故障的关键，同时需要进行告警分级和通知值班人员以便快速响应，最 |
| 3 | Agent Composer | ok | 1 | {"source": "blueprint", "blueprint_id": "BP_INCIDENT_V1", "team": [{"role": "incident_commander", "display_name": "Incident Commander", "skills": ["SKILL_001",  |
| 4 | Incident Commander | ok | 3991 | {"severity": "P1", "need_oncall_notify": true, "initial_plan": ["检查数据库连接池配置，确认最大连接数是否合理", "分析 CPU 使用情况，识别高负载的线程或操作", "查看最近的代码变更，排查可能导致性能问题的提交", "监控数据库性能，确认是否存在慢 |
| 5 | Root Cause Agent | ok | 2535 | {"root_cause": "数据库连接池耗尽导致订单服务无法获取数据库连接，从而引发高CPU和响应时间飙升。", "evidence": ["监控指标显示 db.connections.active=200/200，pending=45，表明连接池已满且有请求在等待。", "日志中出现大量 'HikariPool: |
| 6 | Fix Agent | ok | 5139 | {"steps": [{"order": 1, "action": "增加数据库连接池的最大连接数，调整配置文件中的 'maximumPoolSize' 参数，从 200 增加到 300。", "risk": "中", "est_minutes": 10}, {"order": 2, "action": "优化数据库查 |
| 7 | Verification Agent | ok | 1427 | {"passed": true, "issues": [], "suggestions": [], "score": 1.0, "summary": "任务完成，所有验收标准均满足。"} |

📌 沉淀为 SOP: `SOP_故障处置_CASE_d94` — 数据库连接池耗尽导致订单服务无法获取数据库连接，从而引发高CPU和响应时间飙升。

## Case `CASE_27b391471e` — 订单服务响应超时，疑似数据库连接池耗尽
- scene: **故障处置**, severity: P1
- status: **已完成**
- summary: 任务完成，所有验收标准均满足。

### Agent timeline
| # | Agent | Status | Latency(ms) | Output |
|---:|---|---|---:|---|
| 1 | Scene Router | ok | 1628 | {"scene_type": "故障处置", "confidence": 0.99, "reasoning": "CPU持续高/接口响应时间飙升/用户下单失败，影响严重", "need_confirmation": false} |
| 2 | Skill Retriever | ok | 1687 | {"picked": ["SKILL_001", "SKILL_002", "SKILL_003", "SKILL_004", "SKILL_AUTO_root_cau_CASE_d"], "total_candidates": 8, "reasoning": "根因分析和修复方案设计是解决故障的关键，同时告警分级和通 |
| 3 | Agent Composer | ok | 1 | {"source": "blueprint", "blueprint_id": "BP_INCIDENT_V1", "team": [{"role": "incident_commander", "display_name": "Incident Commander", "skills": ["SKILL_001",  |
| 4 | Incident Commander | ok | 3107 | {"severity": "P1", "need_oncall_notify": true, "initial_plan": ["检查数据库连接池配置，确认最大连接数是否合理", "分析日志，定位连接超时的具体原因", "监控 CPU 使用情况，查看是否有异常请求导致资源占用", "评估是否需要扩展数据库连接池或优化查 |
| 5 | Root Cause Agent | ok | 2668 | {"root_cause": "数据库连接池耗尽导致订单服务无法获取数据库连接，从而引发高CPU使用率和响应时间飙升。", "evidence": ["监控指标显示 db.connections.active=200/200，pending=45，表明连接池已满且有请求在等待。", "日志中出现大量 'HikariPo |
| 6 | Fix Agent | ok | 4992 | {"steps": [{"order": 1, "action": "增加数据库连接池的最大连接数，调整 HikariCP 配置，设置 maxPoolSize 为 300。", "risk": "中", "est_minutes": 10}, {"order": 2, "action": "优化数据库查询，减少不必要的 |
| 7 | Verification Agent | ok | 1194 | {"passed": true, "issues": [], "suggestions": [], "score": 1.0, "summary": "任务完成，所有验收标准均满足。"} |

📌 沉淀为 SOP: `SOP_故障处置_CASE_27b` — 数据库连接池耗尽导致订单服务无法获取数据库连接，从而引发高CPU使用率和响应时间飙升。

## Case `CASE_1b2df8a785` — 深入推进 G 客户 AI 平台商机
- scene: **销售推进**, severity: 
- status: **已失败**
- summary: 交付内容未满足验收标准，缺乏必要的结构化分析和具体建议。

### Agent timeline
| # | Agent | Status | Latency(ms) | Output |
|---:|---|---|---:|---|
| 1 | Scene Router | ok | 1010 | {"scene_type": "销售推进", "confidence": 0.97, "reasoning": "客户沟通、预算、竞品对比、跟进方案需求", "need_confirmation": false} |
| 2 | Skill Retriever | ok | 0 | {"picked": ["SKILL_007", "SKILL_101", "SKILL_102", "SKILL_103", "SKILL_104"], "total_candidates": 5, "reasoning": "候选少，直接全选"} |
| 3 | Agent Composer | ok | 1 | {"source": "blueprint", "blueprint_id": "BP_SALES_V1", "team": [{"role": "customer_profile", "display_name": "客户画像 Agent", "skills": ["SKILL_101"], "desc": "画客户 |
| 4 | 客户画像 Agent | ok | 4106 | {"deliverables": "G 公司是一家规模为 200 人的医疗 SaaS 企业，主要关注 AI 客服和内部知识库的落地。CTO 王总在电话中提到，他们的预算为 200 万，且正在对比我们与另外两家竞品。G 公司对数据本地化、私有部署和合规审计有较高的关注，这表明他们在选择供应商时会考虑数据安全和合规性。王总 |
| 5 | 商机评估 Agent | ok | 8248 | {"deliverables": "根据与 G 公司的沟通，我们可以进行以下 BANT 评估：\n\n1. **预算 (Budget)**: G 公司明确表示其预算为 200 万，符合我们的产品定价范围，评分为 8/10。\n2. **权威 (Authority)**: CTO 王总是决策者，且将在董事会上进行产品推介 |
| 6 | 跟进策略 Agent | ok | 8392 | {"deliverables": "为了有效推进与 G 公司的合作，建议采取以下跟进策略：\n\n1. **准备产品介绍材料**：重点突出我们的数据安全措施、合规性和成功案例，尤其是针对医疗行业的定制化解决方案。确保材料能够清晰地展示我们在数据本地化和私有部署方面的能力，以满足 G 公司的关注点。\n\n2. **安排 |
| 7 | Verification Agent | ok | 5547 | {"passed": false, "issues": ["未提供完整的跟进方案，缺少结构化评估、客户画像分析、商机评估、销售跟进策略和竞品对比等内容。", "没有覆盖行业、规模、采购偏好、决策链等客户画像分析要素。", "缺少结构化评分和可执行推进建议的商机评估。", "未给出3-5步可执行动作的销售跟进策略，包括触 |

## Case `CASE_ac334ddd31` — 高级前端工程师 - 候选人 A 评估
- scene: **招聘流程**, severity: 
- status: **已失败**
- summary: 任务未完成，缺乏必要的评估和建议内容。

### Agent timeline
| # | Agent | Status | Latency(ms) | Output |
|---:|---|---|---:|---|
| 1 | Scene Router | ok | 1902 | {"scene_type": "招聘流程", "confidence": 0.97, "reasoning": "涉及JD、简历筛选、面试题和offer建议", "need_confirmation": false} |
| 2 | Skill Retriever | ok | 0 | {"picked": ["SKILL_007", "SKILL_201", "SKILL_202", "SKILL_203"], "total_candidates": 4, "reasoning": "候选少，直接全选"} |
| 3 | Agent Composer | ok | 1 | {"source": "blueprint", "blueprint_id": "BP_RECRUIT_V1", "team": [{"role": "resume_screener", "display_name": "简历筛选 Agent", "skills": ["SKILL_201"], "desc": "JD |
| 4 | 简历筛选 Agent | ok | 4547 | {"deliverables": "候选人 A 的简历与 JD 匹配度较高，得分为 85 分。候选人拥有 6 年的相关工作经验，符合 5 年以上的要求，并且在创业公司和大厂的经历显示出其在 B 端 SaaS 设计系统方面的能力。候选人主导过 monorepo 改造，虽然没有直接提到微前端经验，但其在大厂的工作背景可能涵 |
| 5 | 面试题 Agent | ok | 4985 | {"deliverables": "候选人 A 的简历与 JD 匹配度较高，得分为 85 分。候选人拥有 6 年的相关工作经验，符合 5 年以上的要求，并且在创业公司和大厂的经历显示出其在 B 端 SaaS 设计系统方面的能力。候选人主导过 monorepo 改造，虽然没有直接提到微前端经验，但其在大厂的工作背景可能涵 |
| 6 | Offer 评估 Agent | ok | 4557 | {"deliverables": "候选人 A 的简历与 JD 匹配度较高，得分为 85 分。候选人拥有 6 年的相关工作经验，符合 5 年以上的要求，并且在创业公司和大厂的经历显示出其在 B 端 SaaS 设计系统方面的能力。候选人主导过 monorepo 改造，虽然没有直接提到微前端经验，但其在大厂的工作背景可能涵 |
| 7 | Verification Agent | ok | 2725 | {"passed": false, "issues": ["未提供简历筛选的分数及匹配/不匹配项", "未生成针对性的面试问题", "未给出具体的 offer 评估及风险提示"], "suggestions": ["提供候选人 A 的简历评分及详细匹配/不匹配项", "生成覆盖技术、协作、文化匹配的面试问题，并附上评估 |

## Case `CASE_f525fd1cae` — 市场部采购 200 套远程会议设备
- scene: **采购审批**, severity: 
- status: **已失败**
- summary: 交付内容缺乏完整性和合规性，未满足验收标准。

### Agent timeline
| # | Agent | Status | Latency(ms) | Output |
|---:|---|---|---:|---|
| 1 | Scene Router | ok | 898 | {"scene_type": "采购审批", "confidence": 0.97, "reasoning": "涉及采购申请和供应商评估", "need_confirmation": false} |
| 2 | Skill Retriever | ok | 0 | {"picked": ["SKILL_005", "SKILL_007", "SKILL_301", "SKILL_302", "SKILL_303"], "total_candidates": 5, "reasoning": "候选少，直接全选"} |
| 3 | Agent Composer | ok | 1 | {"source": "blueprint", "blueprint_id": "BP_PROCURE_V1", "team": [{"role": "requirement_analyst", "display_name": "采购需求 Agent", "skills": ["SKILL_301"], "desc": |
| 4 | 采购需求 Agent | ok | 8607 | {"deliverables": "市场部申请采购200套高清远程会议麦克风+摄像头，总预算为30万元，单价1500元。经过分析，以下是对采购需求的总结与必要性评估：\n\n1. **需求摘要**：市场部需要高清远程会议设备以提升会议质量，满足日常沟通需求，尤其在远程办公日益普及的背景下，确保团队协作的顺畅。\n\n2 |
| 5 | 供应商比价 Agent | ok | 5709 | {"deliverables": "经过对市场部申请采购的200套高清远程会议麦克风+摄像头的需求分析及候选供应商的评估，以下是比价结果及推荐：\n\n1. **比价表**：\n   - **罗技**：单价1620元，交期30天，资质完整。\n   - **雷蛇**：单价1450元，交期45天，缺乏3C认证，存在一定风 |
| 6 | 合规校验 Agent | ok | 3495 | {"deliverables": "经过对市场部申请采购的200套高清远程会议麦克风+摄像头的需求分析及候选供应商的评估，推荐选择罗技作为供应商。虽然罗技的单价（1620元）略高于预算单价（1500元），但其资质完整且交期适中（30天），能够确保设备质量与售后服务，降低采购风险。其他候选供应商雷蛇缺乏3C认证，存在一定 |
| 7 | Verification Agent | ok | 3950 | {"passed": false, "issues": ["未提供审批卡片内容及审批链接，缺乏审批人信息。", "未进行完整的供应商比价，只有三家供应商的比价，但未覆盖所有必要的资质信息。", "缺乏对采购需求的必要性、紧急度和预算合理性的详细分析。", "未逐条对照采购规章进行合规校验，缺乏合规性分析。"], "su |
