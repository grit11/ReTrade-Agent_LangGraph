"""人工服务模块，负责工单创建、认领、决策准备和完成回执。"""
import hashlib
import json
from datetime import datetime, timezone
from retrade_agent.errors import Conflict, AppError


def now():
    """返回当前 UTC 时间字符串。"""
    return datetime.now(timezone.utc).isoformat()


class HumanService:
    """人工工单领域服务，集中处理工单状态流转。"""

    def __init__(self, repo, permission):
        """初始化实例依赖和内部状态。"""
        self.repo = repo
        self.permission = permission

    async def create(self, session_id, customer_id, request_id, kind, reason, summary, data=None):
        # Stable id means retry/replay cannot create duplicate tickets.
        """创建人工工单并保存初始状态。"""
        stable = f"{session_id}|{request_id}|{kind}"
        tid = "TK-" + hashlib.sha256(stable.encode()).hexdigest()[:20]
        return await self.repo.create_ticket(
            {
                "ticket_id": tid,
                "session_id": session_id,
                "customer_id": customer_id,
                "request_id": request_id,
                "kind": kind,
                "reason": reason[:500],
                "summary": summary[:4000],
                "status": "pending",
                "assigned_to": None,
                "data": data or {},
                "created_at": now(),
                "updated_at": now(),
            }
        )

    async def claim(self, actor, ticket_id, version):
        """由员工认领待处理工单。"""
        self.permission.require_staff(actor)
        t = await self.repo.get_ticket(ticket_id)
        if t["status"] not in ("pending", "claimed"):
            raise Conflict("工单当前不能认领")
        if t.get("assigned_to") and t["assigned_to"] != actor.customer_id:
            raise Conflict("工单已由其他客服认领")
        return await self.repo.save_ticket(
            ticket_id, {"assigned_to": actor.customer_id, "status": "claimed"}, version
        )

    async def prepare_decision(self, actor, ticket_id, decision, message, expected_version):
        """校验人工决策并写入待恢复信息。"""
        self.permission.require_staff(actor)
        t = await self.repo.get_ticket(ticket_id)
        allowed = {"approve", "reject"} if t["kind"] == "approval" else {"resolve"}
        if decision not in allowed:
            raise AppError("该工单不支持此处理动作")
        if not message.strip():
            raise AppError("请填写给用户的处理说明")
        payload = {"decision": decision, "message": message.strip(), "staff_id": actor.customer_id}
        if t["status"] == "resolved":
            if t.get("decision") != payload:
                raise Conflict("工单已完成，不能改写处理结论")
            return t
        if t["status"] == "resolving":
            if t.get("decision") != payload:
                raise Conflict("工单正在执行另一个处理结论")
            return t
        if t.get("assigned_to") and t["assigned_to"] != actor.customer_id:
            raise Conflict("工单已由其他客服认领")
        return await self.repo.save_ticket(
            ticket_id,
            {"status": "resolving", "assigned_to": actor.customer_id, "decision": payload},
            expected_version,
        )

    async def complete(self, ticket_id, receipt):
        """保存人工处理完成后的回执。"""
        t = await self.repo.get_ticket(ticket_id)
        if t["status"] == "resolved":
            return t
        return await self.repo.save_ticket(
            ticket_id, {"status": "resolved", "receipt": receipt}, t["version"]
        )
