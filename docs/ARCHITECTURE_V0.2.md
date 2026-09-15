# v0.2 架构说明

请求链路：`FastAPI -> WorkflowService -> SupportGraph -> Agent/SubGraph -> Service -> RAG/Storage`。

人工转接不是技术异常兜底。技术异常返回失败状态并记录日志；人工只用于明确人工诉求、售后人工审核和业务无法自动完成。

RAG：`KnowledgeService -> HybridRetriever -> Vector + BM25 -> RRF -> SiliconFlowReranker`。Retriever 只返回证据，不生成最终答案。

阅读顺序：`models.py -> services -> agents/tools -> agents/runner.py -> graph/support.py -> graph/after_sales.py -> workflow.py -> api`。
