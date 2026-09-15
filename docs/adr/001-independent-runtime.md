# ADR 001：独立工程，不保留 CrewAI Engine

采用 src/retrade_agent 布局。新工程只复制旧知识数据与算法设计；不从 ReTrade_V2 import。
CustomerAgent / OrderAgent 由 create_agent 组装，顶层 LangGraph 负责会话域和受控交接，售后是子图。
Handoff Tool 仅返回结构化 transfer artifact 并 return_direct；父图验证目标和次数后转交。
这样避免多个并行工具同时写父图 active_domain 等标量导致状态冲突，也避免未配对 ToolMessage。
父图持久化经过筛选的公开会话 DTO；子 Agent 内部仍使用框架消息 reducer 与工具协议。
内部工具轨迹不整段复制到另一个 Agent。跨域只传可信订单上下文和公开会话。
