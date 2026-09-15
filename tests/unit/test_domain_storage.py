"""领域服务与持久化单元测试，覆盖权限、幂等、售后策略和本地缓存。"""

import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta
import pytest
from retrade_agent.models import Actor
from retrade_agent.errors import AppError, Conflict, Forbidden, NotFound
from retrade_agent.api.auth import sign_actor, verify_actor
from retrade_agent.storage.cache import LocalCache

A = Actor("demo-customer")
B = Actor("demo-other")
STAFF = Actor("staff-local", "staff")


async def test_order_ownership(orders):
    """验证订单查询仅返回当前客户数据并隐藏非法订单号。"""
    values = await orders.list_orders(A)
    assert values and all(o["customer_id"] == A.customer_id for o in values)
    with pytest.raises(NotFound):
        await orders.get_order(A, "202609140004")
    with pytest.raises(NotFound):
        await orders.get_order(A, "999999999999")
    with pytest.raises(AppError):
        await orders.get_order(A, "x' OR 1=1")


async def test_payment_logistics(orders):
    """验证支付和物流查询返回预期结构。"""
    o = await orders.get_payment(A, "202608090001")
    assert o["simulated"] and o["amount_cents"] > 0
    l = await orders.get_logistics(A, "202608090001")
    assert isinstance(l["events"], list)


async def test_session_ownership(permission):
    """验证会话所有权和员工权限校验。"""
    permission.require_owner(A, A.customer_id)
    with pytest.raises(Forbidden):
        permission.require_owner(A, B.customer_id)
    with pytest.raises(Forbidden):
        permission.require_staff(A)


def test_signed_identity():
    """验证签名身份的生成、解析、过期和篡改保护。"""
    token = sign_actor(A, "test-secret")
    assert verify_actor(token, "test-secret") == A
    with pytest.raises(AppError):
        verify_actor(token + "a", "test-secret")
    with pytest.raises(AppError):
        verify_actor(sign_actor(A, "test-secret", ttl=-1), "test-secret")
    with pytest.raises(AppError):
        verify_actor("bad", "test-secret")


async def test_request_idempotency(repo):
    """验证请求回执幂等及指纹、会话冲突检测。"""
    x = await repo.begin_run("rid", "sid", "fingerprint")
    assert x["status"] == "processing"
    await repo.finish_run("rid", {"reply": "ok"})
    x = await repo.begin_run("rid", "sid", "fingerprint")
    assert x["response"]["reply"] == "ok"
    with pytest.raises(Conflict):
        await repo.begin_run("rid", "sid", "other")
    with pytest.raises(Conflict):
        await repo.begin_run("rid", "other-session", "fingerprint")


async def test_message_dedup_and_restart(repo):
    """验证消息去重和仓储重启后的持久化读取。"""
    await repo.create_session("sid", A.customer_id)
    await repo.add_message("sid", "m1", "user", "问题")
    await repo.add_message("sid", "m1", "user", "问题")
    from retrade_agent.storage.sqlite import SqliteRepository

    restarted = SqliteRepository(repo.path)
    assert len(await restarted.messages("sid")) == 1
    assert (await restarted.get_session("sid"))["customer_id"] == A.customer_id


async def test_session_lease_conflict_and_release(repo):
    """验证会话租约互斥、跨会话并行和释放。"""
    async with repo.lease("sid"):
        with pytest.raises(Conflict):
            async with repo.lease("sid"):
                pass
        async with repo.lease("other"):
            pass
    async with repo.lease("sid"):
        pass


async def test_operation_no_duplicate(repo):
    """验证业务操作结果去重和指纹冲突。"""
    a = await repo.operation("key", "fp", {"id": 1})
    b = await repo.operation("key", "fp", {"id": 2})
    assert a == b == {"id": 1}
    with pytest.raises(Conflict):
        await repo.operation("key", "new-fp", {"id": 1})


async def test_ticket_idempotent_and_optimistic_lock(human, repo):
    """验证人工工单创建幂等和乐观锁。"""
    t = await human.create("sid", A.customer_id, "rid", "support", "reason", "summary")
    same = await human.create("sid", A.customer_id, "rid", "support", "reason", "summary")
    assert t["ticket_id"] == same["ticket_id"]
    updated = await human.claim(STAFF, t["ticket_id"], t["version"])
    assert updated["status"] == "claimed"
    with pytest.raises(Conflict):
        await human.claim(STAFF, t["ticket_id"], t["version"])


async def test_human_decision_auth_types_and_replay(human):
    """验证人工决定的权限、类型约束与结果重放。"""
    t = await human.create("sid", A.customer_id, "rid", "support", "reason", "summary")
    with pytest.raises(Forbidden):
        await human.prepare_decision(A, t["ticket_id"], "resolve", "ok", t["version"])
    with pytest.raises(AppError):
        await human.prepare_decision(STAFF, t["ticket_id"], "approve", "ok", t["version"])
    r = await human.prepare_decision(STAFF, t["ticket_id"], "resolve", "人工结果", t["version"])
    assert r["status"] == "resolving"
    again = await human.prepare_decision(STAFF, t["ticket_id"], "resolve", "人工结果", t["version"])
    assert again["decision"] == r["decision"]
    with pytest.raises(Conflict):
        await human.prepare_decision(STAFF, t["ticket_id"], "resolve", "另一个结论", t["version"])
    await human.complete(t["ticket_id"], {"reply": "done"})
    r = await human.prepare_decision(STAFF, t["ticket_id"], "resolve", "人工结果", t["version"])
    assert r["receipt"]["reply"] == "done"


def case(order_id="202609140001", **fields):
    """构造售后策略测试使用的标准 case 数据。"""
    return {
        "case_id": "CS-testcase0000000001",
        "session_id": "sid",
        "customer_id": A.customer_id,
        "order_id": order_id,
        "issue_type": "return",
        "reason": "不想要",
        "unused": True,
        "customer_confirmed": True,
        **fields,
    }


async def test_policy_low_risk(after_sales, orders):
    """验证低风险售后申请可自动处理。"""
    o = await orders.get_order(A, "202609140001")
    d = after_sales.evaluate(o, case())
    assert d.eligible and d.risk == "low" and not d.requires_manual


async def test_policy_high_amount(after_sales, orders):
    """验证高金额售后申请需要人工审核。"""
    o = await orders.get_order(A, "202609140002")
    d = after_sales.evaluate(o, case(o["order_id"]))
    assert d.eligible and d.requires_manual


async def test_policy_expired(after_sales, orders):
    """验证超过售后期限的申请不可受理。"""
    o = await orders.get_order(A, "202609140003")
    assert not after_sales.evaluate(o, case(o["order_id"])).eligible


@pytest.mark.parametrize("issue", ["damaged", "not_as_described"])
async def test_dispute_requires_review(after_sales, orders, issue):
    """验证争议类问题需要人工审核。"""
    o = await orders.get_order(A, "202609140001")
    assert after_sales.evaluate(o, case(issue_type=issue)).requires_manual


async def test_used_goods_requires_review(after_sales, orders):
    """验证已使用商品的申请需要人工审核。"""
    o = await orders.get_order(A, "202609140001")
    assert after_sales.evaluate(o, case(unused=False)).requires_manual


async def test_unpaid_rejected(after_sales, orders):
    """验证未支付订单的售后申请被拒绝。"""
    o = await orders.get_order(A, "202609140001")
    o["payment_status"] = "unpaid"
    assert not after_sales.evaluate(o, case()).eligible


async def test_confirmation_required(after_sales):
    """验证提交售后操作前必须取得客户确认。"""
    with pytest.raises(Conflict):
        await after_sales.apply(A, case(customer_confirmed=False))


async def test_mock_apply_idempotent(after_sales, repo):
    """验证模拟售后执行幂等并持久化完成状态。"""
    result = await after_sales.apply(A, case())
    repeat = await after_sales.apply(A, case())
    assert result["result"] == repeat["result"] and result["result"]["simulated"]
    assert (await repo.get_case(case()["case_id"]))["status"] == "completed"


async def test_manual_approval_fingerprint(after_sales, orders, human, repo):
    """验证人工审批绑定原始操作指纹并阻止内容变更。"""
    cs = case("202609140002")
    order = await orders.get_order(A, cs["order_id"])
    fp = after_sales.action_fingerprint(cs, order)
    t = await human.create(
        "sid", A.customer_id, cs["case_id"], "approval", "high", "summary", {"action_fingerprint": fp}
    )
    cs["ticket_id"] = t["ticket_id"]
    with pytest.raises(Forbidden):
        await after_sales.apply(A, cs)
    await human.prepare_decision(STAFF, t["ticket_id"], "approve", "已审核", t["version"])
    changed = {**cs, "issue_type": "refund"}
    with pytest.raises(Conflict):
        await after_sales.apply(A, changed)
    done = await after_sales.apply(A, cs)
    assert done["result"]["simulated"]


async def test_cache_ttl_and_ratelimit():
    """验证本地缓存过期和按主体限流。"""
    c = LocalCache()
    await c.put("k", {"reply": "public"}, 1)
    assert (await c.get("k"))["reply"] == "public"
    assert await c.allow("u", 2) and await c.allow("u", 2)
    assert not await c.allow("u", 2)
    assert await c.allow("other", 2)
    await asyncio.sleep(1.05)
    assert await c.get("k") is None
    await c.close()
