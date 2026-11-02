# 复用来源与重写记录

来源仓库：https://github.com/grit11/ReTrade_V2
审核固定提交：0e4cfedd782af897bff105428b5a4f19e38d2940
原始许可证：MIT，Copyright (c) 2026 Liu Bojiang，已在 LICENSE 保留。

| 原资产 | 新路径 | 迁移方式 |
|---|---|---|
| data/knowledge_base.md | resources/knowledge/knowledge_base.md | 原字节复制，git blob SHA b5e63dc90222519a1ad54a672322b6c923ef8c6e |
| eval/dataset/qa.jsonl | eval/datasets/qa.jsonl | 52 条问答迁移且字节校验一致，git blob SHA f760b8c8023a31f68dd766a5c37c8c8d528b065d |
| loader/splitter 设计 | rag/ingestion | 新写有大小限制的 loader 和确定性 chunk ID |
| BM25/RRF | rag/retrieval | 新写平滑 BM25 / 稳定 RRF，非跨项目调用 |
| Milvus/Embedding | infrastructure | 独立 provider 适配；不依赖旧 kb 单例 |
| SiliconFlow rerank | rag/rerank | 新异步 HTTP 客户端，校验索引及分数，有限重试 |
| Order Mock | services + fixtures | 新结构化数据，有归属与状态，保留原演示订单号 |
| Trace/Cache 思路 | application / infrastructure | 新持久化追踪、公共精确缓存和可选 Redis |
| CrewAI/旧 fallback | 不迁移 | 完全重新建立 Parent Graph + Agents |
| API Key | 私有 .env | 仅本地 import_env.py 导入，不把公开历史中的 key 打包 |

官方实现参考：
- https://docs.langchain.com/oss/python/langchain/agents
- https://docs.langchain.com/oss/python/langchain/tools
- https://docs.langchain.com/oss/python/langgraph/use-subgraphs
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://docs.siliconflow.cn/docs/api/rerank-post

依赖声明按 PyPI 元数据核对：LangChain 1.2.18 要求 LangGraph >=1.1.10,<1.2，故使用1.1.10，
不是之前讨论的1.2.11。顶层核心依赖已定版本，但完整跨平台传递依赖锁请在目标环境生成并提交。
当前工程测试入口见根目录 README 的“测试与评估”；不同环境的依赖安装、图运行和外部服务连接需要实际执行验证。
