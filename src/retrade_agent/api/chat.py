import json
import uuid
from fastapi import APIRouter,Depends,Request
from fastapi.responses import StreamingResponse
from retrade_agent.api.auth import authenticate
from retrade_agent.api.schemas import ChatRequest,SessionCreate
from retrade_agent.errors import AppError
router=APIRouter(prefix='/api/v1')

@router.post('/sessions')
async def create_session(body:SessionCreate,request:Request,actor=Depends(authenticate)):
    c=request.app.state.container;sid=str(uuid.uuid4())
    s=await c.repo.create_session(sid,actor.customer_id)
    if body.title:
        await c.repo.update_session(sid,title=body.title);s['title']=body.title
    return s
@router.get('/sessions')
async def sessions(request:Request,actor=Depends(authenticate)):
    return {'sessions':await request.app.state.container.repo.list_sessions(actor.customer_id)}
@router.get('/sessions/{session_id}')
async def session(session_id:uuid.UUID,request:Request,actor=Depends(authenticate)):
    c=request.app.state.container;sid=str(session_id)
    s=await c.workflow.authorize_session(actor,sid)
    return {**s,'messages':await c.repo.messages(sid)}

async def prepare(body,request,actor):
    c=request.app.state.container
    await c.workflow.authorize_session(actor,str(body.session_id))
    if not await c.cache.allow(actor.customer_id,c.settings.rate_limit_per_minute):
        from fastapi import HTTPException
        raise HTTPException(429,'请求过于频繁，请稍后再试')
    return c
@router.post('/chat')
async def chat(body:ChatRequest,request:Request,actor=Depends(authenticate)):
    c=await prepare(body,request,actor)
    return await c.workflow.chat(actor,str(body.session_id),body.message,str(body.request_id))
@router.post('/chat/stream')
async def stream(body:ChatRequest,request:Request,actor=Depends(authenticate)):
    c=await prepare(body,request,actor)
    async def generate():
        try:
            async for event in c.workflow.events(actor,str(body.session_id),body.message,str(body.request_id)):
                yield 'data: '+json.dumps(event,ensure_ascii=False)+'\n\n'
        except AppError as exc:
            yield 'data: '+json.dumps({'type':'error','code':exc.code,'message':exc.message},ensure_ascii=False)+'\n\n'
    return StreamingResponse(generate(),media_type='text/event-stream',
        headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no','X-Content-Type-Options':'nosniff'})
@router.get('/traces/{request_id}')
async def traces(request_id:uuid.UUID,request:Request,actor=Depends(authenticate)):
    c=request.app.state.container;run=await c.repo.get_run(str(request_id))
    if not run:raise AppError('请求记录不存在')
    await c.workflow.authorize_session(actor,run['session_id'])
    return {'events':await c.repo.traces(str(request_id))}
