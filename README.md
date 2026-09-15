# ReTrade Agent · LangGraph v0.2

本版本在 v0.1 基础上重构后端目录，保留原前端设计。重点：

- 后端只保留 `api / agents / graph / services / rag / storage` 六个功能目录；
- CustomerAgent / OrderAgent 使用 LangChain `create_agent`；
- 顶层 `SupportGraph` 管理业务域，`AfterSalesGraph` 管理售后状态机；
- RAG 集中到 `HybridRetriever` 与 `KnowledgeService`；
- 技术故障不再默认创建人工业务工单；
- 人工中断只用于用户明确要求人工、业务高风险审核或真正无法自动处理的业务场景。

## 启动

```powershell
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python scripts/run.py
```

真实模型设置 `APP_MODE=live` 并填写 LLM/Embedding/Rerank 配置。

## 目录

```text
src/retrade_agent/
├── api/       # FastAPI 与 SSE
├── agents/    # Agent、Tool、执行适配
├── graph/     # 顶层图与售后子图
├── services/  # 业务服务
├── rag/       # Loader/BM25/RRF/向量/重排/检索
├── storage/   # SQLite/Postgres接口、Checkpoint、Cache
├── bootstrap.py
├── workflow.py
├── config.py
├── llm.py
├── models.py
└── errors.py
```

原 `frontend/` 完整保留。




src/retrade_agent/

├── api/
│   ├── app.py
│   └── routers/

├── core/
│   ├── config.py
│   ├── llm.py
│   ├── errors.py
│   └── logging.py

├── domain/
│   ├── models.py
│   └── schemas.py

├── agents/
│
├── graph/
│
├── rag/
│
├── services/
│
├── storage/
│
├── bootstrap.py
└── workflow.py
