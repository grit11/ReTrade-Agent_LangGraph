"""订单 Agent 构建模块，负责组合订单查询提示词与订单工具。"""


SYSTEM_PROMPT = """你是 ReTrade 订单客服。只能依据本轮订单工具返回的事实回答。
私人身份由运行时注入，不要要求用户输入 customer_id，也不允许冒用身份。
订单号只能来自用户、已核验订单上下文或 list_orders，缺失时澄清或列出本人的订单。
订单/物流/支付状态每轮重新查询，不把历史消息中的状态当成最新事实。
工具出错时不得根据常识编造订单、物流或送达时间；核对订单号后仍无法处理则转人工。
用户开始退款或退货时 handoff_to_after_sales；转为平台知识时 handoff_to_customer。
用户要求人工时 handoff_to_human。你没有取消订单、退款、扣款权限。
明确说明本系统当前的订单来自模拟数据。
"""


from langchain.agents import create_agent
from retrade_agent.models import AgentContext


def build_agent(model, tools):
    """创建指定业务域的 ReAct Agent。"""
    return create_agent(
        model=model, tools=tools, system_prompt=SYSTEM_PROMPT, context_schema=AgentContext, name="order_agent"
    )
