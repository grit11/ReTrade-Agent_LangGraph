"""真实框架运行测试，覆盖 Agent、嵌套图、持久化、暂停恢复和进程重启。"""
import uuid
import pytest

pytest.importorskip("langgraph", reason="Install project dependencies to run real Graph tests")
pytest.importorskip("langchain", reason="Install project dependencies to run actual create_agent")
from retrade_agent.bootstrap import build_container
from retrade_agent.models import Actor
from retrade_agent.errors import Conflict, Forbidden

pytestmark = pytest.mark.graph
A = Actor("demo-customer")
STAFF = Actor("staff-local", "staff")


async def session(c):
    """为演示客户创建独立测试会话。"""
    sid = str(uuid.uuid4())
    await c.repo.create_session(sid, A.customer_id)
    return sid


async def say(c, sid, text, rid=None):
    """通过统一工作流入口发送一条测试消息。"""
    return await c.workflow.chat(A, sid, text, rid or str(uuid.uuid4()))


async def test_greeting_rag_and_source_reset(settings):
    """验证问候、知识检索及后续轮次来源清理。"""
    async with build_container(settings) as c:
        sid = await session(c)
        r = await say(c, sid, "你好")
        assert r["domain"] == "customer" and r["used_tools"] == []
        r = await say(c, sid, "平台退货规则是什么？")
        assert "search_knowledge" in r["used_tools"] and r["sources"]
        r = await say(c, sid, "谢谢")
        assert not r["sources"]


async def test_order_followup_no_new_triage_and_handoff(settings):
    """验证订单追问复用业务域，并可转回公共知识问答。"""
    async with build_container(settings) as c:
        sid = await session(c)
        r = await say(c, sid, "订单202608090001到哪了？")
        assert (
            r["domain"] == "order" and "get_order" in r["used_tools"] and "get_logistics" in r["used_tools"]
        )
        r = await say(c, sid, "什么时候到？")
        assert r["active_domain"] == "order"
        assert not any(e.get("stage") == "triage" for e in await c.repo.traces(r["request_id"]))
        r = await say(c, sid, "怎么发布商品？")
        assert r["active_domain"] == "customer" and r["sources"]


async def test_after_sales_confirmation_and_dedup(settings):
    """验证售后确认流程和相同请求的幂等结果。"""
    async with build_container(settings) as c:
        sid = await session(c)
        r = await say(c, sid, "订单202609140001我要退货，不想要了，商品未使用")
        assert r["case"]["status"] == "awaiting_confirmation"
        rid = str(uuid.uuid4())
        r = await say(c, sid, "确认提交", rid)
        assert r["case"]["result"]["simulated"] and r["active_domain"] == "customer"
        repeat = await say(c, sid, "确认提交", rid)
        assert repeat["case"] == r["case"]
        with pytest.raises(Conflict):
            await say(c, sid, "不同内容", rid)


async def test_manual_approval_resume_restart(settings):
    """验证人工审核可跨容器重启恢复且结果可重放。"""
    async with build_container(settings) as c:
        sid = await session(c)
        await say(c, sid, "订单202609140002我要退货，不想要了，商品未使用")
        r = await say(c, sid, "确认提交")
        assert r["waiting_human"]
        tid = r["ticket_id"]
        t = await c.repo.get_ticket(tid)
        with pytest.raises(Forbidden):
            await c.workflow.resume(A, tid, "approve", "ok", t["version"], str(uuid.uuid4()))
    # New composition/root, same SQLite files: no in-memory execution state reused.
    async with build_container(settings) as c:
        note = await say(c, sid, "请人工看看")
        assert note["waiting_human"]
        t = await c.repo.get_ticket(tid)
        r = await c.workflow.resume(STAFF, tid, "approve", "已核实，同意模拟申请", t["version"], str(uuid.uuid4()))
        assert r["case"]["status"] == "completed" and r["case"]["result"]["simulated"]
        again = await c.workflow.resume(STAFF, tid, "approve", "已核实，同意模拟申请", t["version"], str(uuid.uuid4()))
        assert again["case"] == r["case"]


async def test_expired_and_support_handoff(settings):
    """验证过期售后拒绝及人工客服转接恢复。"""
    async with build_container(settings) as c:
        sid = await session(c)
        r = await say(c, sid, "订单202609140003我要退货，不想要了，商品未使用")
        assert r["case"]["status"] == "rejected"
        r = await say(c, sid, "我要人工客服")
        assert r["waiting_human"] and r["ticket_id"]
        t = await c.repo.get_ticket(r["ticket_id"])
        r = await c.workflow.resume(
            STAFF, t["ticket_id"], "resolve", "人工客服：问题已记录。", t["version"], str(uuid.uuid4())
        )
        assert r["reply"] == "人工客服：问题已记录。" and not r["waiting_human"]


async def test_order_privacy_and_shared_entry(settings):
    """验证订单隐私保护及事件流共用工作流入口。"""
    async with build_container(settings) as c:
        sid = await session(c)
        r = await say(c, sid, "查询订单202609140004")
        assert r["waiting_human"] and "另一位客户" not in r["reply"]
        sid = await session(c)
        events = [e async for e in c.workflow.events(A, sid, "你好", str(uuid.uuid4()))]
        assert any(e["type"] == "stage" for e in events)
        assert next(e for e in events if e["type"] == "token")["buffered"] is True
        assert events[-1]["type"] == "done"
