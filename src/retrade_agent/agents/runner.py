"""Wrap create_agent subgraphs with input/output adapters and evidence checks.
Only the public reply and verified tool artifacts leave the child graph.
"""
import hashlib
import json
import logging
from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from retrade_agent.models import AgentContext
from retrade_agent.text import GREETINGS

logger = logging.getLogger(__name__)
from retrade_agent.graph.events import emit


def message_text(message):
    """提取消息对象中的文本内容，兼容字符串和内容块格式。"""
    if isinstance(message.content, str):
        return message.content
    return "".join(
        b.get("text", "")
        if isinstance(b, dict) and b.get("type") == "text"
        else b
        if isinstance(b, str)
        else ""
        for b in message.content
    )


class AgentRunner:
    """Agent 执行器，负责运行模型循环、处理工具调用并沉淀运行状态。"""

    def __init__(self, settings, agents, cache, knowledge):
        """初始化实例依赖和内部状态。"""
        self.settings = settings
        self.agents = agents
        self.cache = cache
        self.knowledge = knowledge

    async def run(self, domain, state, config):
        """执行离线结构化抽取或分流逻辑。"""
        emit("stage", stage=domain + "_agent", message="综合客服处理中" if domain == "customer" else "订单客服处理中")
        public = state.get("messages", [])[-20:]
        greeting = state["user_message"].strip("！!。 .").lower() in GREETINGS
        first = sum(m["role"] == "user" for m in public) == 1
        cache_allowed = (
            domain == "customer"
            and first
            and not state.get("current_order_id")
            and not state.get("after_sales_case")
        )
        key = hashlib.sha256(
            json.dumps(
                [
                    state["user_message"].strip(),
                    self.knowledge.retriever.generation,
                    self.settings.app_mode,
                    self.settings.llm_model,
                    "customer-prompt-v1",
                ],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        if cache_allowed and self.settings.cache_enabled:
            cached = await self.cache.get(key)
            if cached:
                emit("stage", stage="cache", message="公共知识缓存命中")
                return {
                    **cached,
                    "active_domain": domain,
                    "result_domain": domain,
                    "cache_hit": True,
                    "used_tools": state.get("used_tools", []),
                    "handoff": None,
                    "need_human": False,
                }
        messages = []
        for m in public:
            cls = HumanMessage if m["role"] == "user" else AIMessage
            messages.append(cls(content=m["content"], id=m.get("id")))
        current = state.get("current_order_id") or "none"
        messages.insert(0, SystemMessage(content=f"服务端可信上下文：current_order_id={current}。仅可访问运行时当前用户自己的订单。"))
        try:
            result = await self.agents[domain].ainvoke(
                {"messages": messages},
                config={**config, "recursion_limit": self.settings.max_agent_steps},
                context=AgentContext(
                    state["customer_id"],
                    state["session_id"],
                    state["request_id"],
                    state.get("current_order_id"),
                ),
            )
        except Exception as exc:
            # 技术故障和业务转人工必须分开。401、超时、协议错误等应先暴露为
            # 可诊断的系统失败，不能为每个技术故障自动创建人工业务工单。
            logger.exception(
                "Agent 执行失败: domain=%s request_id=%s session_id=%s",
                domain,
                state.get("request_id"),
                state.get("session_id"),
            )
            return {
                "need_human": False,
                "final_answer": "智能客服服务暂时不可用，请稍后重试。",
                "status": "failed",
                "error": type(exc).__name__,
                "error_code": "AGENT_EXECUTION_FAILED",
                "result_domain": domain,
                "handoff": None,
            }
        delta = result["messages"][len(messages) :]
        artifacts = [m.artifact for m in delta if isinstance(m, ToolMessage) and isinstance(m.artifact, dict)]
        used = [m.name for m in delta if isinstance(m, ToolMessage) and m.name]
        base = {
            "used_tools": list(dict.fromkeys(state.get("used_tools", []) + used)),
            "result_domain": domain,
            "handoff": None,
            "need_human": False,
            "cache_hit": False,
        }
        usage = {}
        for m in delta:
            if isinstance(m, AIMessage) and m.usage_metadata:
                for k in ("input_tokens", "output_tokens", "total_tokens"):
                    usage[k] = usage.get(k, 0) + m.usage_metadata.get(k, 0)
        base["token_usage"] = {k: state.get("token_usage", {}).get(k, 0) + v for k, v in usage.items()}
        transfers = [a for a in artifacts if a.get("kind") == "handoff"]
        if transfers:
            targets = {a["target"] for a in transfers}
            if len(targets) > 1:
                return {**base, "need_human": True, "handoff_reason": "出现冲突的业务转交指令"}
            return {**base, "handoff": transfers[-1]}
        latest_outcomes = {a.get("tool"): a for a in artifacts if "ok" in a}
        latest_tool_messages = {m.name: m for m in delta if isinstance(m, ToolMessage)}
        protocol_errors = [
            m for m in latest_tool_messages.values() if getattr(m, "status", "success") == "error"
        ]
        failed = [a for a in latest_outcomes.values() if not a["ok"]] + protocol_errors
        if failed:
            return {**base, "need_human": True, "handoff_reason": "业务工具未返回可靠结果，需人工协助"}
        finals = [m for m in delta if isinstance(m, AIMessage) and not m.tool_calls and message_text(m)]
        if not finals:
            return {**base, "need_human": True, "handoff_reason": "未获得有效的最终回复"}
        reply = message_text(finals[-1])
        sources = []
        details = {}
        for a in artifacts:
            if a.get("kind") == "knowledge":
                sources.extend(a.get("sources", []))
                details = a.get("retrieval_detail", {})
            if a.get("kind") == "order" and a.get("ok") and a.get("order_id"):
                base["current_order_id"] = a["order_id"]
        sources = list(dict.fromkeys(sources))
        # Presence of a citation is not assumed because the LLM wrote one: only actual tool artifacts count.
        if domain == "customer" and not greeting and not sources:
            # 没有来源不等于一定需要人工。对于普通交流/澄清允许直接回复；
            # 平台事实应由 Prompt 强制 search_knowledge。若模型没有检索，返回可恢复的
            # clarification 状态，而不是立即把会话锁进人工流程。
            return {
                **base,
                "final_answer": reply,
                "status": "waiting_customer",
                "sources": [],
                "intent": "chat",
                "handoff_reason": "本轮未取得知识库来源",
            }
        if domain == "order" and not any(a.get("kind") == "order" and a.get("ok") for a in artifacts):
            # A harmless clarification can be displayed, but no unverified order fact.
            return {
                **base,
                "final_answer": "请提供需要查询的订单号，或发送“我的订单”查看当前账户的模拟订单。",
                "status": "waiting_customer",
                "sources": [],
                "intent": "order",
            }
        out = {
            **base,
            "final_answer": reply,
            "sources": sources,
            "retrieval_detail": details,
            "status": "responded",
            "intent": "knowledge" if sources else "order" if domain == "order" else "chat",
        }
        if cache_allowed and self.settings.cache_enabled and sources and set(used) == {"search_knowledge"}:
            await self.cache.put(
                key,
                {k: out[k] for k in ("final_answer", "sources", "retrieval_detail", "status", "intent")},
                self.settings.cache_ttl_seconds,
            )
        return out
