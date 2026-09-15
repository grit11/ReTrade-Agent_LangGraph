"""售后子图模块，编排信息收集、订单校验、规则评估、人工审核和模拟申请创建。

工单创建放在独立的可检查点节点中，避免在 interrupt 节点内重复创建工单。
"""
from typing_extensions import TypedDict


class AfterSalesState(TypedDict, total=False):
    """售后子图状态，保存售后流程各节点之间传递的字段。"""

    session_id: str
    request_id: str
    customer_id: str
    user_message: str
    current_order_id: str | None
    case: dict | None
    order: dict
    route: str
    final_answer: str
    status: str
    handoff: dict | None
    ticket_id: str | None


import hashlib
import json
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from retrade_agent.errors import AppError
from retrade_agent.models import Actor, AfterSalesExtraction
from retrade_agent.graph.events import emit


EXTRACTION_PROMPT = """提取当前售后请求。只填写用户明确提供的字段；缺失为 null。
用户在询问公共规则或明确换到订单查询时填写 other_domain。不要把“签收后几天能退”当作实际退款授权。
不要猜订单号、商品状态或退款理由。当前 case 中已有信息由程序合并，勿擅自改写。
"""
CONFIRMS = {"确认提交", "确认申请", "确认", "是，确认提交"}


def build_after_sales(models, orders, service, human):
    """构建售后子图，串联收集、校验、规则、审核和申请节点。"""

    async def collect(state):
        """收集并合并用户提供的售后申请信息。"""
        emit("stage", stage="after_sales.collect_request", message="整理售后信息")
        prior = state.get("case") or {}
        if prior.get("status") in ("completed", "rejected", "cancelled"):
            prior = {}
        cid = (
            prior.get("case_id")
            or "CS-"
            + hashlib.sha256((state["session_id"] + "|" + state["request_id"]).encode()).hexdigest()[:20]
        )
        case = {
            **prior,
            "case_id": cid,
            "session_id": state["session_id"],
            "customer_id": state["customer_id"],
        }
        text = state["user_message"].strip("。！! .")
        if prior.get("status") == "awaiting_confirmation" and text in CONFIRMS:
            case["customer_confirmed"] = True
        else:
            try:
                fields = await models.structured(
                    AfterSalesExtraction,
                    EXTRACTION_PROMPT,
                    json.dumps(
                        {
                            "message": state["user_message"],
                            "current_order_id": state.get("current_order_id"),
                            "case": case,
                        },
                        ensure_ascii=False,
                    ),
                )
            except Exception:
                return {
                    "case": case,
                    "route": "handoff",
                    "handoff": {"target": "human", "reason": "售后信息解析失败"},
                }
            if fields.other_domain:
                return {
                    "case": case,
                    "route": "handoff",
                    "handoff": {"target": fields.other_domain, "reason": "用户切换业务"},
                }
            if fields.cancel:
                case["status"] = "cancelled"
                await service.save_case(case)
                return {
                    "case": case,
                    "route": "end",
                    "status": "completed",
                    "final_answer": "已取消本次模拟售后申请，未执行退款。",
                }
            changed = False
            for key in ("order_id", "issue_type", "reason", "unused"):
                value = getattr(fields, key)
                if value is not None and value != case.get(key):
                    case[key] = value
                    changed = True
            if changed:
                case["customer_confirmed"] = False
        if not case.get("order_id") and state.get("current_order_id"):
            case["order_id"] = state["current_order_id"]
        case.setdefault("status", "draft")
        case.setdefault("customer_confirmed", False)
        if not case.get("order_id"):
            await service.save_case(case)
            return {
                "case": case,
                "route": "end",
                "status": "waiting_customer",
                "final_answer": "请提供售后订单号，以及退款或退货的原因。",
            }
        return {"case": case, "route": "order", "handoff": None}

    async def ensure_order(state):
        """校验售后订单归属并补齐订单关键字段。"""
        case = dict(state["case"])
        emit("stage", stage="after_sales.ensure_order", message="校验订单归属")
        try:
            order = await orders.get_order(Actor(state["customer_id"]), case["order_id"])
        except AppError as exc:
            case["status"] = "draft"
            await service.save_case(case)
            return {
                "case": case,
                "route": "end",
                "status": "waiting_customer",
                "final_answer": exc.message + "，请重新提供订单号。",
            }
        case["amount_cents"] = order["amount_cents"]
        case["product"] = order["product"]
        if not case.get("issue_type") or not case.get("reason"):
            await service.save_case(case)
            return {
                "case": case,
                "order": order,
                "route": "end",
                "status": "waiting_customer",
                "final_answer": f"已找到模拟订单 {order['order_id']}（{order['product']}）。请说明申请类型和原因，例如：退货，不想要了，商品未使用。",
            }
        if order.get("delivered_at") and case["issue_type"] in ("refund", "return") and "unused" not in case:
            await service.save_case(case)
            return {
                "case": case,
                "order": order,
                "route": "end",
                "status": "waiting_customer",
                "final_answer": "请确认商品是否未使用、附件完整且不影响二次销售。",
            }
        return {"case": case, "order": order, "route": "policy"}

    async def policy(state):
        """执行售后规则评估并决定确认、拒绝、审核或申请。"""
        emit("stage", stage="after_sales.policy_check", message="执行售后资格与风险规则")
        case = dict(state["case"])
        decision = service.evaluate(state["order"], case)
        case["policy"] = decision.model_dump()
        case["risk_level"] = decision.risk
        if not decision.eligible:
            case["status"] = "rejected"
            await service.save_case(case)
            return {
                "case": case,
                "route": "end",
                "status": "rejected",
                "final_answer": "本次模拟申请未通过自动资格校验：" + decision.reason + "。如有异议可要求人工客服。",
            }
        if not case.get("customer_confirmed"):
            case["status"] = "awaiting_confirmation"
            await service.save_case(case)
            text = (
                f"请确认模拟售后申请：订单 {case['order_id']}，商品 {case['product']}，金额 ¥{case['amount_cents']/100:.2f}，"
                f"原因：{case['reason']}。风险等级：{decision.risk}。回复“确认提交”继续；未确认前不会创建售后申请。此操作不发生真实退款。"
            )
            return {"case": case, "route": "end", "status": "waiting_customer", "final_answer": text}
        await service.save_case(case)
        return {"case": case, "route": "review" if decision.requires_manual else "apply"}

    async def prepare_review(state):
        """为高风险售后申请创建人工审核工单。"""
        case = dict(state["case"])
        fp = service.action_fingerprint(case, state["order"])
        ticket = await human.create(
            state["session_id"],
            state["customer_id"],
            case["case_id"],
            "approval",
            case["policy"]["reason"],
            f"模拟售后：{case['order_id']} / {case['reason']}",
            {
                "case_id": case["case_id"],
                "order_id": case["order_id"],
                "amount_cents": case["amount_cents"],
                "action_fingerprint": fp,
                "simulated": True,
            },
        )
        case.update(ticket_id=ticket["ticket_id"], status="waiting_human")
        await service.save_case(case)
        emit("stage", stage="after_sales.human_review", message="等待人工审核")
        return {"case": case, "ticket_id": ticket["ticket_id"], "status": "waiting_human"}

    async def review(state):
        # DO NOT catch this interrupt or create a ticket before it in this node.
        """等待人工审核结果并决定是否继续创建申请。"""
        decision = interrupt(
            {
                "kind": "approval",
                "ticket_id": state["ticket_id"],
                "case_id": state["case"]["case_id"],
                "reason": state["case"]["policy"]["reason"],
            }
        )
        if not isinstance(decision, dict) or decision.get("ticket_id") != state["ticket_id"]:
            raise ValueError("Resume ticket mismatch")
        if decision["decision"] == "approve":
            return {"route": "apply"}
        case = {**state["case"], "status": "rejected"}
        await service.save_case(case)
        return {
            "case": case,
            "route": "end",
            "status": "rejected",
            "final_answer": "人工审核未通过：" + decision["message"] + "。未执行真实退款。",
        }

    async def apply(state):
        """调用售后服务创建幂等模拟申请，并生成最终回复。"""
        emit("stage", stage="after_sales.apply", message="创建幂等模拟售后申请")
        case = await service.apply(Actor(state["customer_id"]), state["case"])
        result = case["result"]
        return {
            "case": case,
            "status": "completed",
            "final_answer": f"{result['message']}。申请编号：{result['application_id']}。",
        }

    g = StateGraph(AfterSalesState)
    for name, node in [
        ("collect_request", collect),
        ("ensure_order", ensure_order),
        ("policy_check", policy),
        ("prepare_review", prepare_review),
        ("human_review", review),
        ("apply", apply),
    ]:
        g.add_node(name, node)
    g.add_edge(START, "collect_request")
    g.add_conditional_edges(
        "collect_request", lambda s: s["route"], {"order": "ensure_order", "end": END, "handoff": END}
    )
    g.add_conditional_edges("ensure_order", lambda s: s["route"], {"policy": "policy_check", "end": END})
    g.add_conditional_edges(
        "policy_check", lambda s: s["route"], {"review": "prepare_review", "apply": "apply", "end": END}
    )
    g.add_edge("prepare_review", "human_review")
    g.add_conditional_edges("human_review", lambda s: s["route"], {"apply": "apply", "end": END})
    g.add_edge("apply", END)
    return g.compile(name="after_sales_subgraph")
