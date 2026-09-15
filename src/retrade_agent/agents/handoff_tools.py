"""子 Agent 通过 return_direct 结束执行，由父图校验并执行业务转交。

工具命令不会并发写入父图的标量状态。
"""
import json
from langchain.tools import tool


def build_handoff_tools(domain):
    """按当前业务域生成允许使用的转接工具列表。"""

    def result(target, reason, order_id=None):
        """构造标准化转接工具返回值。"""
        artifact = {"kind": "handoff", "target": target, "reason": reason[:500], "order_id": order_id}
        return json.dumps({"handoff_requested": target}, ensure_ascii=False), artifact

    @tool(return_direct=True, response_format="content_and_artifact")
    def handoff_to_order(reason: str, order_id: str | None = None) -> tuple[str, dict]:
        """用户开始查询私人订单/物流时，将后续会话控制权交给订单客服。"""
        return result("order", reason, order_id)

    @tool(return_direct=True, response_format="content_and_artifact")
    def handoff_to_after_sales(reason: str, order_id: str | None = None) -> tuple[str, dict]:
        """用户明确要申请退款/退货/质量售后时交给售后流程；单纯询问规则不用转交。"""
        return result("after_sales", reason, order_id)

    @tool(return_direct=True, response_format="content_and_artifact")
    def handoff_to_human(reason: str) -> tuple[str, dict]:
        """用户要求真人客服、可靠资料不足或工具失败无法处理时请求人工接管。"""
        return result("human", reason)

    @tool(return_direct=True, response_format="content_and_artifact")
    def handoff_to_customer(reason: str) -> tuple[str, dict]:
        """当前问题转为平台使用、公开政策或普通咨询时转回综合客服。"""
        return result("customer", reason)

    return (
        [handoff_to_order, handoff_to_after_sales, handoff_to_human]
        if domain == "customer"
        else [handoff_to_customer, handoff_to_after_sales, handoff_to_human]
    )
