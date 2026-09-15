"""聊天会话 API 路由模块，提供会话创建、消息发送、SSE 流和追踪查询。"""
import json
import uuid
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from retrade_agent.api.auth import authenticate
from retrade_agent.api.schemas import ChatRequest, SessionCreate
from retrade_agent.errors import AppError

router = APIRouter(prefix="/api/v1")


@router.post("/sessions")
async def create_session(body: SessionCreate, request: Request, actor=Depends(authenticate)):
    """创建当前客户的新聊天会话。"""
    c = request.app.state.container
    sid = str(uuid.uuid4())
    s = await c.repo.create_session(sid, actor.customer_id)
    if body.title:
        await c.repo.update_session(sid, title=body.title)
        s["title"] = body.title
    return s


@router.get("/sessions")
async def sessions(request: Request, actor=Depends(authenticate)):
    """列出当前客户的最近会话。"""
    return {"sessions": await request.app.state.container.repo.list_sessions(actor.customer_id)}


@router.get("/sessions/{session_id}")
async def session(session_id: uuid.UUID, request: Request, actor=Depends(authenticate)):
    """读取当前客户指定会话详情。"""
    c = request.app.state.container
    sid = str(session_id)
    s = await c.workflow.authorize_session(actor, sid)
    return {**s, "messages": await c.repo.messages(sid)}


async def prepare(body, request, actor):
    """为聊天请求补齐 request_id，便于前端发起幂等请求。"""
    c = request.app.state.container
    await c.workflow.authorize_session(actor, str(body.session_id))
    if not await c.cache.allow(actor.customer_id, c.settings.rate_limit_per_minute):
        from fastapi import HTTPException

        raise HTTPException(429, "请求过于频繁，请稍后再试")
    return c


@router.post("/chat")
async def chat(body: ChatRequest, request: Request, actor=Depends(authenticate)):
    """处理普通非流式聊天接口请求。"""
    c = await prepare(body, request, actor)
    return await c.workflow.chat(actor, str(body.session_id), body.message, str(body.request_id))


@router.post("/chat/stream")
async def stream(body: ChatRequest, request: Request, actor=Depends(authenticate)):
    """以 SSE 形式推送聊天处理阶段和最终结果。"""
    c = await prepare(body, request, actor)

    async def generate():
        """把工作流事件转换为 SSE 文本帧。"""
        try:
            async for event in c.workflow.events(
                actor, str(body.session_id), body.message, str(body.request_id)
            ):
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        except AppError as exc:
            yield "data: " + json.dumps(
                {"type": "error", "code": exc.code, "message": exc.message}, ensure_ascii=False
            ) + "\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/traces/{request_id}")
async def traces(request_id: uuid.UUID, request: Request, actor=Depends(authenticate)):
    """查询指定 request_id 的执行追踪事件。"""
    c = request.app.state.container
    run = await c.repo.get_run(str(request_id))
    if not run:
        raise AppError("请求记录不存在")
    await c.workflow.authorize_session(actor, run["session_id"])
    return {"events": await c.repo.traces(str(request_id))}
