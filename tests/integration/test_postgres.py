"""可选 PostgreSQL 集成测试，在随机 schema 中验证仓储与图恢复。

设置 RETRADE_TEST_POSTGRES_DSN 后执行；不使用默认业务表、不调用付费模型。
每个测试只清理自己创建的 schema，现有数据库业务记录不受影响。
"""

import asyncio
import json
import os
import sys
import uuid

import pytest

from retrade_agent.bootstrap import build_container
from retrade_agent.config import PROJECT_ROOT, Settings
from retrade_agent.errors import Conflict, NotFound
from retrade_agent.models import Actor

pytestmark = pytest.mark.skipif(
    not os.environ.get("RETRADE_TEST_POSTGRES_DSN"),
    reason="Set RETRADE_TEST_POSTGRES_DSN to run isolated PostgreSQL integration tests",
)


@pytest.fixture(scope="module")
def event_loop_policy():
    """为 Windows psycopg 提供 Selector 事件循环，Linux 使用默认循环。"""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
async def pg_settings(tmp_path):
    """创建独立 schema，配置离线图和 PostgreSQL 双后端，结束时清理。"""
    psycopg = pytest.importorskip("psycopg")
    from psycopg.conninfo import make_conninfo
    from psycopg.sql import Identifier, SQL

    schema = "retrade_test_" + uuid.uuid4().hex
    dsn = os.environ["RETRADE_TEST_POSTGRES_DSN"]
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        await conn.execute(SQL("CREATE SCHEMA {}").format(Identifier(schema)))
    isolated_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    try:
        yield Settings(
            _env_file=None,
            app_env="test",
            app_mode="offline",
            storage_backend="postgres",
            checkpoint_backend="postgres",
            async_database_url=isolated_dsn,
            langgraph_database_url=isolated_dsn,
            data_dir=tmp_path,
            vector_store="local",
            redis_url="",
        )
    finally:
        async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
            await conn.execute(SQL("DROP SCHEMA {} CASCADE").format(Identifier(schema)))


@pytest.fixture
async def pg_repo(pg_settings):
    """打开仓储并初始化隔离的演示订单。"""
    from retrade_agent.storage.postgres import PostgresRepository

    repo = PostgresRepository(pg_settings)
    try:
        await repo.open()
        seed = json.loads((PROJECT_ROOT / "resources/fixtures/orders.json").read_text(encoding="utf-8"))
        await repo.setup(seed)
        yield repo
    finally:
        await repo.close()


async def test_entities_and_knowledge(pg_repo):
    """验证 Unicode、版本、文档向量和缺失记录的接口兼容性。"""
    repo = pg_repo
    first = await repo.create_session("会话一", "客户甲")
    assert first["version"] == 1
    assert await repo.create_session("会话一", "客户乙") == first
    await repo.create_session("会话二", "客户乙")
    await repo.update_session("会话一", title="退货咨询")
    current = await repo.get_session("会话一")
    assert current["version"] == 2 and current["title"] == "退货咨询"
    assert current["updated_at"] >= first["updated_at"]
    assert len(await repo.list_sessions("客户甲")) == 1
    with pytest.raises(NotFound):
        await repo.get_case("不存在")
    document = {"document_id": "文档一", "text": "中文政策", "vectors": [[0.1, 0.2]]}
    await repo.put_document(document)
    assert (await repo.knowledge())[0]["vectors"] == document["vectors"]
    await repo.delete_document("文档一")
    assert await repo.knowledge() == []
    await repo.save_case({"case_id": "售后一", "status": "collecting"})
    assert (await repo.get_case("售后一"))["status"] == "collecting"
    stats = await repo.stats()
    assert stats["sessions"] == 2 and stats["cases"] == 1 and stats["order"] == 5


async def test_messages_runs_and_reopen(pg_repo, pg_settings):
    """验证消息顺序、重复请求、追踪与跨连接池的持久化读取。"""
    from retrade_agent.storage.postgres import PostgresRepository

    for number in range(4):
        await pg_repo.add_message("sid", f"m{number}", "user", f"消息{number}")
    await pg_repo.add_message("sid", "m3", "user", "重复内容不应覆盖")
    assert [m["content"] for m in await pg_repo.messages("sid", 2)] == ["消息2", "消息3"]
    await pg_repo.begin_run("rid", "sid", "指纹")
    await pg_repo.finish_run("rid", {"reply": "完成", "nested": [None, True]})
    with pytest.raises(Conflict):
        await pg_repo.begin_run("rid", "sid", "不同指纹")
    with pytest.raises(Conflict):
        await pg_repo.begin_run("rid", "other", "指纹")
    await pg_repo.append_trace("rid", "sid", {"type": "stage", "message": "处理中"})
    reopened = PostgresRepository(pg_settings)
    try:
        await reopened.open()
        assert (await reopened.begin_run("rid", "sid", "指纹"))["response"]["reply"] == "完成"
        assert (await reopened.get_run("rid"))["status"] == "done"
        assert await reopened.get_run("missing") is None
        assert len(await reopened.messages("sid")) == 4
        assert (await reopened.traces("rid"))[0]["message"] == "处理中"
    finally:
        await reopened.close()


async def test_concurrent_updates_operations_and_leases(pg_repo, pg_settings):
    """验证并发乐观锁、操作幂等以及不同连接池之间的会话互斥。"""
    from retrade_agent.storage.postgres import PostgresRepository

    ticket = await pg_repo.create_ticket({"ticket_id": "ticket", "status": "pending"})
    results = await asyncio.gather(
        *(
            pg_repo.save_ticket("ticket", {"status": state}, ticket["version"])
            for state in ("claimed", "resolved")
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, Conflict) for result in results) == 1
    assert (await pg_repo.get_ticket("ticket"))["version"] == 2
    receipts = await asyncio.gather(
        *(pg_repo.operation("operation", "fingerprint", {"n": n}) for n in range(6))
    )
    assert all(receipt == receipts[0] for receipt in receipts)
    with pytest.raises(Conflict):
        await pg_repo.operation("operation", "different", {})
    other = PostgresRepository(pg_settings)
    try:
        await other.open()
        async with pg_repo.lease("sid"):
            with pytest.raises(Conflict):
                async with other.lease("sid"):
                    pass
            async with other.lease("other"):
                pass
        async with other.lease("sid"):
            pass
    finally:
        await other.close()


async def say(container, sid, message, rid=None):
    """通过真实工作流处理离线消息。"""
    return await container.workflow.chat(Actor("demo-customer"), sid, message, rid or str(uuid.uuid4()))


async def test_workflow_query_and_confirm(pg_settings):
    """验证混合检索、订单工具、售后确认及请求重放均使用 PostgreSQL。"""
    async with build_container(pg_settings) as c:
        sid = str(uuid.uuid4())
        await c.repo.create_session(sid, "demo-customer")
        reply = await say(c, sid, "平台退货规则是什么？")
        assert reply["sources"] and "search_knowledge" in reply["used_tools"]
        # 各域使用独立会话；本测试关注存储链路，跨域语言理解由业务测试覆盖。
        sid = str(uuid.uuid4())
        await c.repo.create_session(sid, "demo-customer")
        reply = await say(c, sid, "订单202608090001到哪了？")
        assert "get_logistics" in reply["used_tools"]
        sid = str(uuid.uuid4())
        await c.repo.create_session(sid, "demo-customer")
        reply = await say(c, sid, "订单202609140001我要退货，不想要了，商品未使用")
        assert reply["case"]["status"] == "awaiting_confirmation"
        rid = str(uuid.uuid4())
        reply = await say(c, sid, "确认提交", rid)
        assert reply["case"]["status"] == "completed"
        assert (await say(c, sid, "确认提交", rid))["case"] == reply["case"]


@pytest.mark.parametrize("decision", ["approve", "reject", "resolve"])
async def test_restart_and_human_resume(pg_settings, decision):
    """验证审批与客服工单在连接池/图重建后可恢复且只生成一次回执。"""
    sid = str(uuid.uuid4())
    async with build_container(pg_settings) as c:
        await c.repo.create_session(sid, "demo-customer")
        if decision == "resolve":
            reply = await say(c, sid, "我要人工客服")
        else:
            await say(c, sid, "订单202609140002我要退货，不想要了，商品未使用")
            reply = await say(c, sid, "确认提交")
        assert reply["waiting_human"]
        tid = reply["ticket_id"]
    async with build_container(pg_settings) as c:
        assert (await say(c, sid, "补充说明"))["waiting_human"]
        ticket = await c.repo.get_ticket(tid)
        staff = Actor("staff-local", "staff")
        result = await c.workflow.resume(
            staff, tid, decision, "人工处理完成", ticket["version"], str(uuid.uuid4())
        )
        assert not result["waiting_human"]
        if decision != "resolve":
            assert result["case"]["status"] == ("completed" if decision == "approve" else "rejected")
        repeat = await c.workflow.resume(
            staff, tid, decision, "人工处理完成", ticket["version"], str(uuid.uuid4())
        )
        assert repeat == result
