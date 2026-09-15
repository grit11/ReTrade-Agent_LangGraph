"""Explicit scripted test model. It is NOT a language model and is never used in live mode.
It emits real AIMessage.tool_calls so offline runs still execute create_agent/ToolNode
and the real Parent Graph. Test behavior does not prove online model answer quality.
"""
import json
import re
import uuid
from typing import Any
from pydantic import Field
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from retrade_agent.text import GREETINGS, human_requested


def order_id_from(text):
    """从用户文本中提取模拟订单号。"""
    m = re.search(r"(?<!\d)\d{6,20}(?!\d)", text)
    return m.group(0) if m else None


def is_after_sales(text):
    """判断文本是否表达售后、退款、退货或换货诉求。"""
    policy_only = any(x in text for x in ("规则", "政策", "几天", "多久", "运费", "什么是", "支持七天", "支持退货"))
    action = any(
        x in text for x in ("我要退", "帮我退", "申请退款", "申请退货", "申请售后", "退掉", "确认提交", "商品坏了", "收到了破损", "不想要了")
    )
    return action or (
        order_id_from(text) is not None
        and any(x in text for x in ("退款", "退货", "损坏", "破损"))
        and not policy_only
    )


def _plain(message):
    """把聊天消息统一转换为可检索的纯文本。"""
    return message.content if isinstance(message.content, str) else ""


class OfflineChatModel(BaseChatModel):
    """离线聊天模型，模拟结构化输出和工具调用，避免本地演示依赖外部模型。"""

    tool_names: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self):
        """返回离线模型在 LangChain 中使用的类型标识。"""
        return "offline-scripted-fixture"

    def bind_tools(self, tools, **kwargs):
        """记录当前模型可使用的工具列表并返回自身。"""
        names = [getattr(t, "name", None) or t.get("function", {}).get("name", "") for t in tools]
        return self.model_copy(update={"tool_names": names})

    def with_structured_output(self, schema, **kwargs):
        """创建离线结构化输出适配器。"""

        def run(messages):
            """执行离线结构化抽取或分流逻辑。"""
            text = _plain(messages[-1])
            try:
                data = json.loads(text)
                text = data.get("message", text)
            except (ValueError, TypeError):
                data = {}
            if schema.__name__ == "TriageResult":
                domain = (
                    "human"
                    if human_requested(text)
                    else "after_sales"
                    if is_after_sales(text)
                    else "order"
                    if any(x in text for x in ("订单", "物流", "到哪", "发货"))
                    and not any(x in text for x in ("如何下单", "怎么下单"))
                    else "customer"
                )
                return schema(domain=domain, reason="离线测试规则，不代表模型判定", confidence=1.0)
            if schema.__name__ == "AfterSalesExtraction":
                issue = (
                    "damaged"
                    if any(x in text for x in ("破损", "坏了", "损坏"))
                    else "not_as_described"
                    if "描述不符" in text
                    else "return"
                    if any(x in text for x in ("退货", "不想要"))
                    else "refund"
                    if "退款" in text
                    else None
                )
                unused = (
                    True
                    if any(x in text for x in ("未使用", "没用过", "没拆封", "没有用过"))
                    else False
                    if any(x in text for x in ("用过", "使用过", "拆封"))
                    else None
                )
                other = (
                    "order"
                    if "另一单物流" in text or "先查物流" in text
                    else "customer"
                    if any(x in text for x in ("先聊别的", "怎么发布", "平台规则"))
                    else None
                )
                reason = next((s for s in ("不想要", "拍错", "破损", "损坏", "商品坏了", "描述不符") if s in text), None)
                return schema(
                    order_id=order_id_from(text),
                    issue_type=issue,
                    reason=reason,
                    unused=unused,
                    cancel=any(x in text for x in ("取消申请", "不退了")),
                    other_domain=other,
                )
            raise NotImplementedError(f"No offline fixture for {schema.__name__}")

        return RunnableLambda(run)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        """根据离线规则生成 AIMessage，并按需附带工具调用。"""
        latest = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
        text = _plain(messages[latest]) if latest >= 0 else ""
        observations = [m for m in messages[latest + 1 :] if isinstance(m, ToolMessage)]
        context = "\n".join(_plain(m) for m in messages if isinstance(m, SystemMessage))
        oid = order_id_from(text)
        if not oid:
            match = re.search(r"current_order_id=([0-9]{6,20})", context)
            oid = match.group(1) if match else None

        def call(name, args):
            """调用绑定工具并返回工具消息。"""
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": name, "args": args, "id": "call_" + uuid.uuid4().hex[:16], "type": "tool_call"}
                ],
            )

        if observations:
            m = observations[-1]
            try:
                value = json.loads(_plain(m))
            except ValueError:
                value = {}
            if value.get("ok") is False:
                msg = AIMessage(content="当前工具没有提供可靠结果，我会请求人工协助。")
            elif m.name == "search_knowledge":
                cs = value.get("contexts", [])
                ss = value.get("sources", [])
                body = "\n\n".join(f"{c}\n[{s}]" for c, s in zip(cs[:2], ss[:2]))
                msg = AIMessage(content=("【离线演示 · 摘录示例知识库】\n" + body) if cs else "当前知识库没有足够资料，需要人工协助。")
            elif m.name == "get_order" and any(x in text for x in ("物流", "到哪", "没到", "什么时候到")):
                msg = call("get_logistics", {"order_id": value["data"]["order_id"]})
            else:
                d = value.get("data", {})
                if isinstance(d, list):
                    body = "\n".join(f"{o['order_id']} · {o['product']} · {o['status']}" for o in d)
                    msg = AIMessage(content="【模拟订单】\n" + body + "\n请告诉我需要处理的订单号。")
                elif m.name == "get_logistics":
                    body = "；".join(e["status"] for e in d.get("events", []))
                    msg = AIMessage(content=f"【模拟物流】订单 {d.get('order_id','')}：{body}。")
                elif m.name == "get_payment_status":
                    msg = AIMessage(
                        content=f"【模拟支付】订单 {d.get('order_id')}：{d.get('payment_status')}，金额 ¥{d.get('amount_cents',0)/100:.2f}。"
                    )
                else:
                    msg = AIMessage(
                        content=f"【模拟订单】{d.get('order_id','')} · {d.get('product','')}，状态：{d.get('status','')}。"
                    )
        elif human_requested(text):
            msg = call("handoff_to_human", {"reason": "用户明确要求人工客服"})
        elif is_after_sales(text) and "handoff_to_after_sales" in self.tool_names:
            msg = call("handoff_to_after_sales", {"reason": "用户开始售后流程", "order_id": oid})
        elif "search_knowledge" in self.tool_names:
            if any(x in text for x in ("查订单", "订单到哪", "物流", "我的订单", "查一下订单")):
                msg = call("handoff_to_order", {"reason": "需要查询个人订单", "order_id": oid})
            elif text.strip("！!。 .").lower() in GREETINGS:
                msg = AIMessage(content="你好，我是 ReTrade 客服助手。可以咨询平台规则、查询订单或申请售后。当前为离线演示模式。")
            else:
                msg = call("search_knowledge", {"query": text})
        elif any(x in text for x in ("怎么发布", "平台规则", "联系卖家", "服务费", "普通聊天")):
            msg = call("handoff_to_customer", {"reason": "转回公共咨询"})
        elif not oid:
            msg = call("list_orders", {})
        elif "支付" in text:
            msg = call("get_payment_status", {"order_id": oid})
        else:
            msg = call("get_order", {"order_id": oid})
        return ChatResult(generations=[ChatGeneration(message=msg)])
