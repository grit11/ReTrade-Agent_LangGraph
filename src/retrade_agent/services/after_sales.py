"""Deterministic MOCK policy and idempotent MOCK application creation. No money API."""
import hashlib
import json
from datetime import datetime, timezone
from retrade_agent.errors import Conflict, Forbidden
from retrade_agent.models import PolicyDecision


class AfterSalesService:
    """售后领域服务，集中处理规则评估与模拟申请落库。"""

    def __init__(self, repo, orders):
        """初始化实例依赖和内部状态。"""
        self.repo = repo
        self.orders = orders

    async def save_case(self, case: dict) -> dict:
        """保存售后 case 的最新状态。"""
        return await self.repo.save_case(case)

    def evaluate(self, order: dict, case: dict) -> PolicyDecision:
        """根据订单和售后信息计算模拟规则决策。"""
        issue = case.get("issue_type")
        if order["payment_status"] != "paid":
            return PolicyDecision(eligible=False, risk="low", reason="订单未支付，不适用退款申请")
        if order["status"] in ("cancelled", "refunded"):
            return PolicyDecision(eligible=False, risk="low", reason="订单已关闭或已退款")
        if issue in ("damaged", "not_as_described"):
            return PolicyDecision(eligible=True, risk="high", reason="质量或描述争议需要人工查看凭证", requires_manual=True)
        if order["special_category"]:
            return PolicyDecision(eligible=False, risk="low", reason="示例规则：特殊商品不支持无理由退货")
        delivered = order.get("delivered_at")
        if delivered:
            days = (datetime.now(timezone.utc) - datetime.fromisoformat(delivered)).total_seconds() / 86400
            if days > 7:
                return PolicyDecision(eligible=False, risk="low", reason="示例规则：超过签收后 7 天的自动退货窗口")
        if case.get("unused") is False:
            return PolicyDecision(eligible=True, risk="medium", reason="商品已使用，需人工核实状态", requires_manual=True)
        if not delivered:
            return PolicyDecision(
                eligible=True, risk="medium", reason="运输中售后需要人工确认拦截或退回", requires_manual=True
            )
        if order["amount_cents"] >= 100000:
            return PolicyDecision(eligible=True, risk="high", reason="模拟规则：金额达到人工审核阈值", requires_manual=True)
        return PolicyDecision(eligible=True, risk="low", reason="满足示例自动处理条件；仅创建模拟申请")

    @staticmethod
    def action_fingerprint(case, order):
        """为售后申请生成幂等业务指纹。"""
        content = {
            "case_id": case["case_id"],
            "order_id": order["order_id"],
            "customer_id": order["customer_id"],
            "issue_type": case["issue_type"],
            "amount_cents": order["amount_cents"],
            "policy_version": "mock-policy-v1",
        }
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    async def apply(self, actor, case):
        """执行模拟售后申请的幂等落库逻辑。"""
        order = await self.orders.get_order(actor, case["order_id"])
        decision = self.evaluate(order, case)  # Recheck at the write boundary.
        if not case.get("customer_confirmed"):
            raise Conflict("需要先由用户确认提交")
        if not decision.eligible:
            raise Conflict(decision.reason)
        fingerprint = self.action_fingerprint(case, order)
        if decision.requires_manual:
            ticket = await self.repo.get_ticket(case["ticket_id"])
            approved = ticket.get("decision", {})
            if ticket["status"] not in ("resolving", "resolved") or approved.get("decision") != "approve":
                raise Forbidden("需要经鉴权的人工审核批准")
            if ticket["data"].get("action_fingerprint") != fingerprint:
                raise Conflict("审批后业务参数发生变化，需要重新审核")
        result = {
            "application_id": "AS-" + case["case_id"][-12:].upper(),
            "order_id": case["order_id"],
            "amount_cents": order["amount_cents"],
            "status": "simulated_submitted",
            "simulated": True,
            "message": "模拟售后申请已创建，未调用支付平台、未执行真实退款",
        }
        result = await self.repo.operation("after-sales:" + case["case_id"], fingerprint, result)
        case = {**case, "status": "completed", "result": result}
        await self.repo.save_case(case)
        return case
