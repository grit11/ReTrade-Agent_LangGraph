"""API 合同测试，通过显式工作流替身验证接口而不模拟 LangGraph 运行时。"""
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
    """提供稳定响应的工作流替身，用于隔离 API 合同测试。"""

    def __init__(self, repo, permission):
        """保存合同测试所需的仓储和权限服务。"""
        self.repo = repo
        self.permission = permission

    async def authorize_session(self, actor, sid):
        """校验请求者对测试会话的访问权限。"""
        s = await self.repo.get_session(sid)
        self.permission.require_owner(actor, s["customer_id"])
        return s

    async def chat(self, actor, sid, text, rid):
        """返回固定结构的聊天合同响应。"""
        await self.authorize_session(actor, sid)
        return {
            "reply": "接口合同响应",
            "session_id": sid,
            "request_id": rid,
            "engine": "langgraph",
            "domain": "customer",
            "status": "responded",
            "used_tools": [],
        }

    async def events(self, actor, sid, text, rid):
        """按固定顺序生成流式合同事件。"""
        yield {"type": "stage", "stage": "contract_fixture"}
        yield {"type": "token", "content": "接口合同响应", "buffered": True}
        yield {"type": "done", **await self.chat(actor, sid, text, rid)}


@pytest.fixture
def client(settings, repo, orders, after_sales, human, permission):
    """创建注入合同工作流替身的 FastAPI 测试客户端。"""
    k = SimpleNamespace(last_error=None, retriever=SimpleNamespace(chunks=[1]))
    c = Container(
        settings,
        repo,
        permission,
        LocalCache(),
        k,
        orders,
        after_sales,
        human,
        ContractWorkflow(repo, permission),
        [],
    )
    with TestClient(create_app(settings, c)) as client:
        yield client


def session(client, user="demo-customer"):
    """登录指定演示用户并创建 API 测试会话。"""
    assert client.post("/api/v1/auth/demo", json={"user": user}).status_code == 200
    return client.post("/api/v1/sessions", json={}).json()["session_id"]


def test_frontend_and_public_health(client):
    """验证前端静态资源、公开健康信息和安全响应头。"""
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    h = client.get("/health").json()
    assert h["app_mode"] == "offline" and "api_key" not in str(h)
    assert client.get("/").headers["x-content-type-options"] == "nosniff"


def test_login_required(client):
    """验证会话接口要求登录身份。"""
    assert client.get("/api/v1/sessions").status_code == 401


def test_customer_cannot_admin(client):
    """验证普通客户不能访问管理接口。"""
    session(client)
    assert client.get("/api/v1/human/tickets").status_code == 403
    assert client.get("/api/v1/knowledge").status_code == 403
    assert client.post("/api/v1/human/resume", json={}).status_code in (403, 422)


def test_session_isolation(client):
    """验证不同客户之间的会话访问隔离。"""
    sid = session(client)
    session(client, "demo-other")
    assert client.get("/api/v1/sessions/" + sid).status_code == 403
    assert client.post("/api/v1/chat", json={"session_id": sid, "message": "hello"}).status_code == 403


def test_model_identity_field_forbidden(client):
    """验证聊天请求不能自行注入客户身份字段。"""
    sid = session(client)
    assert (
        client.post(
            "/api/v1/chat", json={"session_id": sid, "message": "hi", "customer_id": "other"}
        ).status_code
        == 422
    )


def test_json_and_sse_contract(client):
    """验证普通 JSON 与 SSE 聊天接口的响应合同。"""
    sid = session(client)
    r = client.post("/api/v1/chat", json={"session_id": sid, "message": "hi"})
    assert r.status_code == 200
    s = client.post("/api/v1/chat/stream", json={"session_id": sid, "message": "hi"})
    assert s.status_code == 200 and "text/event-stream" in s.headers["content-type"]
    assert '"type": "done"' in s.text and "接口合同响应" in s.text


def test_admin_token_and_origin(client):
    """验证管理令牌和跨站来源限制。"""
    assert client.get("/api/v1/stats", headers={"X-Admin-Token": "bad"}).status_code == 401
    assert client.get("/api/v1/stats", headers={"X-Admin-Token": "dev-admin-change-me"}).status_code == 200
    assert (
        client.post("/api/v1/auth/demo", json={}, headers={"Origin": "https://evil.test"}).status_code == 403
    )
