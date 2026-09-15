"""人工客服 API 路由模块，提供工单列表、认领、留言和人工决策恢复。"""
import uuid
from fastapi import APIRouter, Request, Depends
from retrade_agent.api.auth import require_staff
from retrade_agent.api.schemas import HumanResume, TicketClaim, TicketMessage
from retrade_agent.errors import Conflict

router = APIRouter(prefix="/api/v1/human")


@router.get("/tickets")
async def tickets(request: Request, status: str | None = None, actor=Depends(require_staff)):
    """列出员工可见的人工工单。"""
    return {"tickets": await request.app.state.container.repo.list_tickets(status)}


@router.get("/tickets/{ticket_id}")
async def ticket(ticket_id: str, request: Request, actor=Depends(require_staff)):
    """读取单个人工工单详情。"""
    c = request.app.state.container
    t = await c.repo.get_ticket(ticket_id)
    return {**t, "messages": await c.repo.messages(t["session_id"])}


@router.post("/tickets/{ticket_id}/claim")
async def claim(ticket_id: str, body: TicketClaim, request: Request, actor=Depends(require_staff)):
    """由员工认领待处理工单。"""
    return await request.app.state.container.human.claim(actor, ticket_id, body.expected_version)


@router.post("/tickets/{ticket_id}/messages")
async def comment(ticket_id: str, body: TicketMessage, request: Request, actor=Depends(require_staff)):
    """向工单追加内部或处理留言。"""
    c = request.app.state.container
    t = await c.repo.get_ticket(ticket_id)
    if t["status"] not in ("pending", "claimed"):
        raise Conflict("工单已结束或正在恢复")
    await c.repo.add_message(
        t["session_id"], "staff-note:" + str(uuid.uuid4()), "assistant", "【人工客服】" + body.message
    )
    return {"ok": True}


@router.post("/resume")
async def resume(body: HumanResume, request: Request, actor=Depends(require_staff)):
    """处理人工审核或人工客服恢复接口请求。"""
    return await request.app.state.container.workflow.resume(
        actor, body.ticket_id, body.decision, body.message, body.expected_version, str(body.request_id)
    )
