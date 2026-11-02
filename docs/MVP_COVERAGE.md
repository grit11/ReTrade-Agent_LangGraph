# MVP → 当前实现映射

基线：docs/mvp/ 下的原设计。交付版本 v0.1.0；本轮范围以用户最新要求为准。

| MVP 要求 | 实现入口 | 状态 |
|---|---|---|
| 独立项目、无 Crew 运行时 | pyproject.toml / src/retrade_agent | 已实现 |
| CustomerAgent + RAG | graph/agents/customer, tools/knowledge_tools.py | 已实现 create_agent |
| OrderAgent | graph/agents/order, tools/order_tools.py | 已实现，订单数据模拟 |
| active_domain / triage / handoff | graph/parent/builder.py | 已实现；限制交接次数 |
| 自定义售后子图 | graph/subgraphs/after_sales | 收集/归属/规则/确认/审批/模拟提交 |
| 人工介入 | services/human_service + human API | 工单/认领/回复/interrupt/resume |
| 前后端重新设计 | api/ + frontend/ | 会话、轨迹、来源、工单、知识中心 |
| BM25 + RRF + vector | rag/ + infrastructure/vectorstore | 新实现，local/Milvus 可切换 |
| SiliconFlow 重排 | rag/rerank/siliconflow.py | 只接远程 API；失败标明降级 |
| 持久化 | SQLite repo + 官方 SQLite saver | 本轮默认；支持进程重启恢复 |
| PostgreSQL | StoragePort / `PostgresRepository` / optional saver | 已实现业务 JSONB 仓储与 LangGraph 检查点适配；需安装 `.[postgres]` |
| Redis | infrastructure/cache/cache.py | 可选缓存/限流，未配置使用本地 TTL |
| 权限 | api/auth.py + PermissionService | 开发签名身份、订单归属、工单管理令牌 |
| 真实资金操作 | AfterSalesService | **不实现**；只创建幂等模拟申请 |
| 流式输出 | application/workflow.events + SSE | 实时阶段；答案经校验后缓冲发布 |
| 测试/评测 | tests/ + eval/ | 单元/接口合同/真实 Graph 测试脚本 |

公开身份、消息、私有订单由服务端鉴权，customer_id 不进入 LLM 可填写参数。
政策数据是旧项目的示例业务数据，不代表任何真实平台或法律承诺。
证据门控能检查是否调用了检索与返回来源，不能形式化证明模型每句话都忠于资料；需真实模型评测。
不提供多租户、多机器 HA、完整生产 SSO、真实订单微服务、生产 SLA 的完成承诺。
