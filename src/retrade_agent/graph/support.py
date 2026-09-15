"""Parent workflow owns routing and handoff. It never calls Milvus/SQL directly."""
import json
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langchain_core.runnables import RunnableConfig
from retrade_agent.models import TriageResult
from retrade_agent.text import human_requested
from retrade_agent.graph.events import emit
from .state import CustomerServiceState

TRIAGE_PROMPT = """你是客服业务分诊器，不回答用户。
customer=平台公共介绍、使用帮助、规则、普通聊天；询问退货政策仍归 customer。
order=查询具体订单、物流、支付状态。
after_sales=实际申请退款退货、商品损坏或描述争议的处理流程。
human=用户明确要求人工客服。
只返回结构化域与简短理由；confidence 不是授权依据。
"""


def build_parent(settings, models, agent_runner, after_sales, human, checkpointer):
    """构建客服主图并连接各业务节点。"""

    async def hydrate(state):
        """从持久化会话中恢复当前业务上下文。"""
        emit("stage", stage="hydrate_context", message="加载会话与可信身份")
        # This node is not rerun when a later node resumes from interrupt.
        update = {
            "sources": [],
            "used_tools": [],
            "retrieval_detail": {},
            "token_usage": {},
            "handoff": None,
            "handoff_count": 0,
            "need_human": False,
            "final_answer": "",
            "error": None,
            "cache_hit": False,
            "human_ticket_id": None,
            "status": "active",
            "intent": "chat",
            "result_domain": state.get("active_domain") or "customer",
        }
        prior_case = state.get("after_sales_case") or {}
        if state.get("active_domain") != "after_sales" and prior_case.get("status") in (
            "completed",
            "rejected",
            "cancelled",
        ):
            update["after_sales_case"] = None
        if human_requested(state["user_message"]):
            update.update(need_human=True, handoff_reason="用户明确要求人工客服")
        return update

    def initial_route(state):
        """根据已有等待状态决定是否直接进入人工处理。"""
        if state.get("need_human"):
            return "human"
        return "dispatch" if state.get("active_domain") in ("customer", "order", "after_sales") else "triage"

    async def triage(state):
        """调用结构化模型判断用户消息应进入哪个业务域。"""
        emit("stage", stage="triage", message="首次业务分诊")
        try:
            r = await models.structured(TriageResult, TRIAGE_PROMPT, state["user_message"])
            return {"active_domain": r.domain, "triage_reason": r.reason, "triage_confidence": r.confidence}
        except Exception as exc:
            return {"active_domain": "human", "handoff_reason": "业务分诊服务暂不可用", "error": type(exc).__name__}

    async def dispatch(state):
        """根据分流结果确定下一步业务节点。"""
        emit("domain", domain=state["active_domain"])
        return {"result_domain": state["active_domain"]}

    async def customer(state: CustomerServiceState, config: RunnableConfig):
        """执行客户通用咨询 Agent。"""
        return await agent_runner.run("customer", state, config)

    async def order(state: CustomerServiceState, config: RunnableConfig):
        """执行订单查询 Agent。"""
        return await agent_runner.run("order", state, config)

    async def after_sales_node(state: CustomerServiceState, config: RunnableConfig):
        # Never catch GraphInterrupt here. Parent runtime persists the nested checkpoint.
        """执行售后子图并合并子图输出。"""
        result = await after_sales.ainvoke(
            {
                "session_id": state["session_id"],
                "request_id": state["request_id"],
                "customer_id": state["customer_id"],
                "user_message": state["user_message"],
                "current_order_id": state.get("current_order_id"),
                "case": state.get("after_sales_case"),
            },
            config=config,
        )
        case = result.get("case")
        out = {
            "after_sales_case": case,
            "result_domain": "after_sales",
            "intent": "after_sale_rule",
            "handoff": result.get("handoff"),
            "final_answer": result.get("final_answer", ""),
            "status": result.get("status", "responded"),
            "sources": [],
        }
        if result.get("order"):
            out["current_order_id"] = result["order"]["order_id"]
        if out["status"] in ("completed", "rejected"):
            out["active_domain"] = "customer"
        return out

    async def assess(state):
        """检查 Agent 输出是否需要转接或人工介入。"""
        transfer = state.get("handoff")
        if transfer:
            if transfer.get("target") not in ("customer", "order", "after_sales", "human"):
                return {"need_human": True, "handoff_reason": "业务转交目标无效", "handoff": None}
            if state["handoff_count"] >= settings.max_handoffs:
                return {"need_human": True, "handoff_reason": "业务转交超过次数限制", "handoff": None}
        return {}

    def route_result(state):
        """根据当前状态选择结束、人工或转接路径。"""
        if state.get("need_human"):
            return "human"
        if state.get("handoff"):
            return "handoff"
        return "finalize"

    async def handoff(state):
        """记录跨域转接意图并更新活跃业务域。"""
        transfer = state["handoff"]
        target = transfer["target"]
        emit(
            "handoff",
            from_domain=state.get("active_domain"),
            to_domain=target,
            reason=transfer.get("reason", ""),
        )
        out = {
            "prior_domain": state.get("active_domain"),
            "active_domain": target,
            "handoff": None,
            "handoff_reason": transfer.get("reason", "业务转交"),
            "handoff_count": state["handoff_count"] + 1,
        }
        if transfer.get("order_id"):
            out["current_order_id"] = transfer["order_id"]
        return out

    async def prepare_human(state):
        """创建人工工单并把会话置为等待人工状态。"""
        summary = "\n".join(f"{m['role']}: {m['content']}" for m in state.get("messages", [])[-8:])
        t = await human.create(
            state["session_id"],
            state["customer_id"],
            state["request_id"],
            "support",
            state.get("handoff_reason") or "需要人工协助",
            summary,
            {"prior_domain": state.get("active_domain"), "order_id": state.get("current_order_id")},
        )
        return {
            "prior_domain": state.get("active_domain"),
            "active_domain": "human",
            "human_ticket_id": t["ticket_id"],
            "status": "waiting_human",
            "final_answer": "已为你转接人工客服。等待期间可继续补充信息，AI 不会擅自恢复业务操作。",
        }

    async def wait_human(state):
        """触发人工暂停点，等待客服恢复。"""
        reply = interrupt(
            {
                "kind": "support",
                "ticket_id": state["human_ticket_id"],
                "reason": state.get("handoff_reason", ""),
            }
        )
        if not isinstance(reply, dict) or reply.get("ticket_id") != state["human_ticket_id"]:
            raise ValueError("Resume ticket mismatch")
        return {
            "final_answer": reply["message"],
            "active_domain": "customer",
            "result_domain": "human",
            "intent": "human",
            "status": "responded",
            "need_human": False,
            "human_ticket_id": None,
        }

    async def finalize(state):
        """汇总图执行后的最终回复状态。"""
        emit("stage", stage="finalize", message="保存已校验的回复")
        answer = state.get("final_answer") or "暂时无法完成该请求，请稍后重试或转人工。"
        messages = list(state.get("messages", [])) + [
            {"id": "assistant:" + state["request_id"], "role": "assistant", "content": answer}
        ]
        return {"final_answer": answer, "messages": messages[-24:]}

    g = StateGraph(CustomerServiceState)
    for name, node in [
        ("hydrate_context", hydrate),
        ("triage", triage),
        ("dispatch", dispatch),
        ("customer_agent", customer),
        ("order_agent", order),
        ("after_sales", after_sales_node),
        ("assess_result", assess),
        ("apply_handoff", handoff),
        ("prepare_human", prepare_human),
        ("await_human", wait_human),
        ("finalize", finalize),
    ]:
        g.add_node(name, node)
    g.add_edge(START, "hydrate_context")
    g.add_conditional_edges(
        "hydrate_context",
        initial_route,
        {"human": "prepare_human", "triage": "triage", "dispatch": "dispatch"},
    )
    g.add_edge("triage", "dispatch")
    g.add_conditional_edges(
        "dispatch",
        lambda s: s["active_domain"],
        {
            "customer": "customer_agent",
            "order": "order_agent",
            "after_sales": "after_sales",
            "human": "prepare_human",
        },
    )
    for node in ("customer_agent", "order_agent", "after_sales"):
        g.add_edge(node, "assess_result")
    g.add_conditional_edges(
        "assess_result",
        route_result,
        {"human": "prepare_human", "handoff": "apply_handoff", "finalize": "finalize"},
    )
    g.add_edge("apply_handoff", "dispatch")
    g.add_edge("prepare_human", "await_human")
    g.add_edge("await_human", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer, name="customer_service_graph")
