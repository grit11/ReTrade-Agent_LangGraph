"""App factory + lifespan, with same-origin redesigned frontend. No business logic here."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request,Depends
from fastapi.responses import JSONResponse,FileResponse
from fastapi.staticfiles import StaticFiles
from retrade_agent.config import Settings,PROJECT_ROOT
from retrade_agent.errors import AppError,Forbidden
from retrade_agent.api.auth import sign_actor,authenticate,require_staff
from retrade_agent.api.schemas import DemoLogin
from retrade_agent.models import Actor
from retrade_agent.api import chat,human,knowledge

def create_app(settings:Settings|None=None,container=None):
    settings=settings or Settings()
    @asynccontextmanager
    async def lifespan(app):
        if container is not None:
            app.state.container=container
            yield
        else:
            from retrade_agent.bootstrap import build_container
            async with build_container(settings) as c:
                app.state.container=c
                yield
    app=FastAPI(title='ReTrade Agent · LangGraph',version='0.1.0',lifespan=lifespan)
    @app.exception_handler(AppError)
    async def app_error(request,exc):
        return JSONResponse(status_code=exc.status_code,content={'error':{'code':exc.code,'message':exc.message}})
    @app.exception_handler(Exception)
    async def unknown_error(request,exc):
        logging.getLogger('retrade').error('unhandled error type=%s path=%s',type(exc).__name__,request.url.path)
        return JSONResponse(status_code=500,content={'error':{'code':'INTERNAL_ERROR','message':'服务异常，请查看本地日志或联系维护者'}})
    @app.middleware('http')
    async def security_headers(request,call_next):
        # Cross-origin browser writes are not allowed, including admin actions.
        if request.method in ('POST','PUT','PATCH','DELETE'):
            origin=request.headers.get('origin')
            if origin and origin!=str(request.base_url).rstrip('/'):
                return JSONResponse(status_code=403,content={'error':{'code':'ORIGIN_DENIED','message':'跨站请求被拒绝'}})
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response
    @app.get('/health')
    async def health():
        c=app.state.container
        return {'status':'degraded' if c.knowledge.last_error else 'ok',**settings.public_info(),
                'knowledge_ready':bool(c.knowledge.retriever.chunks) and not c.knowledge.last_error,
                'warnings':c.startup_warnings or []}
    @app.post('/api/v1/auth/demo')
    async def demo_login(body:DemoLogin):
        if settings.app_env=='prod':raise Forbidden('生产环境禁用演示身份，请接入身份服务')
        actor=Actor(body.user)
        token=sign_actor(actor,settings.auth_secret.get_secret_value())
        response=JSONResponse({'customer_id':body.user,'role':'customer'})
        response.set_cookie('retrade_session',token,httponly=True,samesite='strict',secure=settings.app_env=='prod',max_age=28800)
        return response
    @app.get('/api/v1/auth/me')
    async def me(actor=Depends(authenticate)):
        return {'customer_id':actor.customer_id,'role':actor.role}
    @app.get('/api/v1/orders')
    async def orders(actor=Depends(authenticate)):
        return {'orders':await app.state.container.orders.list_orders(actor),'simulated':True}
    @app.get('/api/v1/stats')
    async def stats(actor=Depends(require_staff)):
        return await app.state.container.repo.stats()
    app.include_router(chat.router);app.include_router(human.router);app.include_router(knowledge.router)
    front=PROJECT_ROOT/'frontend'
    app.mount('/static',StaticFiles(directory=front),name='static')
    @app.get('/',include_in_schema=False)
    async def index():return FileResponse(front/'index.html')
    return app

app=create_app()
