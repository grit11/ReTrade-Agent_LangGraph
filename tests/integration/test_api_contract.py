"""API contract tests with an explicitly injected workflow double.
These do NOT claim to test LangGraph. See tests/graph for actual runtime tests.
"""
import asyncio
import uuid
from types import SimpleNamespace
from fastapi.testclient import TestClient
import pytest
from retrade_agent.api.app import create_app
from retrade_agent.bootstrap import Container
from retrade_agent.storage.cache import LocalCache
from retrade_agent.errors import AppError

class ContractWorkflow:
    def __init__(self,repo,permission):self.repo=repo;self.permission=permission
    async def authorize_session(self,actor,sid):
        s=await self.repo.get_session(sid);self.permission.require_owner(actor,s['customer_id']);return s
    async def chat(self,actor,sid,text,rid):
        await self.authorize_session(actor,sid)
        return {'reply':'接口合同响应','session_id':sid,'request_id':rid,'engine':'langgraph','domain':'customer','status':'responded','used_tools':[]}
    async def events(self,actor,sid,text,rid):
        yield {'type':'stage','stage':'contract_fixture'}
        yield {'type':'token','content':'接口合同响应','buffered':True}
        yield {'type':'done',**await self.chat(actor,sid,text,rid)}

@pytest.fixture
def client(settings,repo,orders,after_sales,human,permission):
    k=SimpleNamespace(last_error=None,retriever=SimpleNamespace(chunks=[1]))
    c=Container(settings,repo,permission,LocalCache(),k,orders,after_sales,human,ContractWorkflow(repo,permission),[])
    with TestClient(create_app(settings,c)) as client:yield client

def session(client,user='demo-customer'):
    assert client.post('/api/v1/auth/demo',json={'user':user}).status_code==200
    return client.post('/api/v1/sessions',json={}).json()['session_id']
def test_frontend_and_public_health(client):
    assert client.get('/').status_code==200
    assert client.get('/static/app.js').status_code==200
    h=client.get('/health').json();assert h['app_mode']=='offline' and 'api_key' not in str(h)
    assert client.get('/').headers['x-content-type-options']=='nosniff'
def test_login_required(client):assert client.get('/api/v1/sessions').status_code==401
def test_customer_cannot_admin(client):
    session(client);assert client.get('/api/v1/human/tickets').status_code==403
    assert client.get('/api/v1/knowledge').status_code==403
    assert client.post('/api/v1/human/resume',json={}).status_code in (403,422)
def test_session_isolation(client):
    sid=session(client)
    session(client,'demo-other')
    assert client.get('/api/v1/sessions/'+sid).status_code==403
    assert client.post('/api/v1/chat',json={'session_id':sid,'message':'hello'}).status_code==403
def test_model_identity_field_forbidden(client):
    sid=session(client)
    assert client.post('/api/v1/chat',json={'session_id':sid,'message':'hi','customer_id':'other'}).status_code==422
def test_json_and_sse_contract(client):
    sid=session(client)
    r=client.post('/api/v1/chat',json={'session_id':sid,'message':'hi'});assert r.status_code==200
    s=client.post('/api/v1/chat/stream',json={'session_id':sid,'message':'hi'})
    assert s.status_code==200 and 'text/event-stream' in s.headers['content-type']
    assert '"type": "done"' in s.text and '接口合同响应' in s.text
def test_admin_token_and_origin(client):
    assert client.get('/api/v1/stats',headers={'X-Admin-Token':'bad'}).status_code==401
    assert client.get('/api/v1/stats',headers={'X-Admin-Token':'dev-admin-change-me'}).status_code==200
    assert client.post('/api/v1/auth/demo',json={},headers={'Origin':'https://evil.test'}).status_code==403
