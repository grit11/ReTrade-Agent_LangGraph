"""Fault injection against real local runtime; external HTTP uses MockTransport."""

import asyncio
import tempfile
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from unittest.mock import patch
from evaluation.common import DATA, read_jsonl, select, settings_for, metadata
from evaluation.metrics import success_summary


async def must_raise(exc_type, awaitable):
    try:
        await awaitable
    except exc_type:
        return True
    raise AssertionError(f"Expected {exc_type.__name__}")


async def execute(name, s):
    import httpx
    from retrade_agent.bootstrap import build_container
    from retrade_agent.models import Actor
    from retrade_agent.errors import Conflict, Forbidden, Unavailable
    from retrade_agent.api.app import create_app
    from retrade_agent.storage.clients import request_json
    from retrade_agent.rag.reranker import SiliconFlowReranker
    from retrade_agent.agents.offline import OfflineChatModel
    from evaluation.runners import count_operations

    actor = Actor("demo-customer")
    staff = Actor("staff-local", "staff")
    checks = []

    def check(label, condition):
        checks.append({"name": label, "passed": bool(condition)})

    async with AsyncExitStack() as stack:
        c = await stack.enter_async_context(build_container(s))
        sid = str(uuid.uuid4())
        await c.repo.create_session(sid, actor.customer_id)

        async def say(text, rid=None):
            return await c.workflow.chat(actor, sid, text, rid or str(uuid.uuid4()))

        async def setup_approval():
            await say("订单202609140002我要退货，不想要了，商品未使用")
            r = await say("确认提交")
            assert r["waiting_human"]
            return await c.repo.get_ticket(r["ticket_id"])

        if name == "request_replay":
            rid = str(uuid.uuid4())
            a = await say("你好", rid)
            b = await say("你好", rid)
            check("same_answer", a["reply"] == b["reply"])
            check("replayed", b.get("replayed"))
            check("two_messages", len(await c.repo.messages(sid)) == 2)
        elif name == "request_conflict":
            rid = str(uuid.uuid4())
            await say("你好", rid)
            check("conflict", await must_raise(Conflict, say("不同文本", rid)))
        elif name == "lease_conflict":
            async with c.repo.lease(sid):
                check("conflict", await must_raise(Conflict, say("你好")))
            check("released", (await say("你好"))["status"] == "responded")
        elif name == "operation_idempotency":
            a = await c.repo.operation("eval-op", "fp", {"n": 1})
            b = await c.repo.operation("eval-op", "fp", {"n": 2})
            check("same_receipt", a == b == {"n": 1})
            check(
                "fingerprint_conflict",
                await must_raise(Conflict, c.repo.operation("eval-op", "other", {"n": 3})),
            )
            check("single_operation", await count_operations(c.repo) == 1)
        elif name == "session_isolation":
            app = create_app(s, c)
            app.state.container = c
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                login = await client.post("/api/v1/auth/demo", json={"user": "demo-other"})
                check("login", login.status_code == 200)
                check("read_denied", (await client.get("/api/v1/sessions/" + sid)).status_code == 403)
                check(
                    "write_denied",
                    (
                        await client.post("/api/v1/chat", json={"session_id": sid, "message": "你好"})
                    ).status_code
                    == 403,
                )
        elif name == "api_identity":
            app = create_app(s, c)
            app.state.container = c
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/auth/demo", json={"user": "demo-customer"})
                r = await client.post(
                    "/api/v1/chat", json={"session_id": sid, "message": "你好", "customer_id": "demo-other"}
                )
                check("unexpected_identity_rejected", r.status_code == 422)
                check("admin_denied", (await client.get("/api/v1/human/tickets")).status_code == 403)
        elif name == "approval_auth":
            t = await setup_approval()
            check(
                "forbidden",
                await must_raise(
                    Forbidden,
                    c.workflow.resume(
                        actor, t["ticket_id"], "approve", "test", t["version"], str(uuid.uuid4())
                    ),
                ),
            )
            check("no_write", await count_operations(c.repo) == 0)
        elif name == "checkpoint_restart":
            t = await setup_approval()
            await stack.aclose()
            c = await stack.enter_async_context(build_container(s))
            r = await c.workflow.resume(
                staff, t["ticket_id"], "approve", "已核实", t["version"], str(uuid.uuid4())
            )
            check("resumed", r.get("case", {}).get("status") == "completed")
            check("single_write", await count_operations(c.repo) == 1)
        elif name == "vector_failure":

            async def fail(*a, **kw):
                raise TimeoutError("injected")

            with patch.object(c.knowledge.retriever.vectors, "search", fail):
                r = await c.knowledge.search("退货规则")
            check("bm25_available", bool(r.contexts))
            check("degradation_visible", r.detail.get("degraded"))
        elif name == "rerank_failure":
            ss = s.model_copy(update={"app_mode": "live"})
            from pydantic import SecretStr

            ss.rerank_api_key = SecretStr("mock-only")
            http = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(503, json={})))
            rerank = SiliconFlowReranker(ss, http)

            async def no_sleep(*a):
                pass

            try:
                with patch("retrade_agent.storage.clients.asyncio.sleep", no_sleep):
                    chunks = c.knowledge.retriever.chunks[:3]
                    result, detail = await rerank.rerank("退货", chunks, 2)
                check("fallback_order", result == chunks[:2])
                check("failure_visible", detail.get("reason") == "upstream_failed")
            finally:
                await rerank.close()
        elif name == "agent_timeout":
            # Bypass initial triage so the injected exception targets AgentRunner.
            await say("你好")

            def fail(*a, **kw):
                raise TimeoutError("injected fixture timeout")

            with patch.object(OfflineChatModel, "_generate", fail):
                r = await say("平台退货规则是什么？")
            check("failed_status", r.get("status") == "failed")
            check("no_business_ticket", not r.get("waiting_human"))
        elif name == "tool_failure":

            async def fail(*a, **kw):
                raise Unavailable("注入订单服务不可用")

            with patch.object(c.orders, "get_order", fail):
                r = await say("查询订单202609140001")
            check("no_false_success", "复古机械键盘" not in r["reply"])
            check("no_operation", await count_operations(c.repo) == 0)
            check("current_policy_handoff", r.get("waiting_human"))
        elif name == "ticket_version":
            t = await c.human.create(sid, actor.customer_id, "r", "support", "test", "test")
            await c.human.claim(staff, t["ticket_id"], t["version"])
            check(
                "stale_version_conflict",
                await must_raise(Conflict, c.human.claim(staff, t["ticket_id"], t["version"])),
            )
        elif name == "http_retry":
            calls = []

            def respond(req):
                calls.append(1)
                return httpx.Response(503 if len(calls) < 3 else 200, json={"ok": True})

            async def no_sleep(*a):
                pass

            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                with patch("retrade_agent.storage.clients.asyncio.sleep", no_sleep):
                    r = await request_json(client, "https://fixture.invalid/api", "mock", {})
            check("three_attempts", len(calls) == 3 and r["ok"])
            calls = []

            def unauthorized(req):
                calls.append(1)
                return httpx.Response(401, json={})

            async with httpx.AsyncClient(transport=httpx.MockTransport(unauthorized)) as client:
                check(
                    "401_raised",
                    await must_raise(
                        httpx.HTTPStatusError, request_json(client, "https://fixture.invalid/api", "mock", {})
                    ),
                )
            check("401_no_retry", len(calls) == 1)
        elif name == "cache_generation":
            before = c.knowledge.retriever.generation
            await c.knowledge.ingest("evaluation-only.txt", "评测新增说明：配送查询必须提供订单号。".encode())
            after = c.knowledge.retriever.generation
            check("generation_changed", before != after)
            doc = next(d for d in await c.knowledge.list_documents() if d["title"] == "evaluation-only.txt")
            await c.knowledge.remove(doc["document_id"])
            check("generation_restored", c.knowledge.retriever.generation == before)
        elif name == "client_cancel":
            entered = asyncio.Event()
            original = c.orders.get_order
            rid = str(uuid.uuid4())

            async def blocked(*a, **kw):
                entered.set()
                await asyncio.Event().wait()
                return await original(*a, **kw)

            with patch.object(c.orders, "get_order", blocked):
                task = asyncio.create_task(say("查询订单202609140001", rid))
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            run = await c.repo.get_run(rid)
            check("cancel_recorded", run["status"] == "failed")
            check("no_write", await count_operations(c.repo) == 0)
            async with c.repo.lease(sid):
                check("lease_released", True)
        else:
            raise ValueError("Unknown reliability scenario " + name)
    return checks


async def reliability(args):
    if args.mode != "offline":
        raise ValueError("Fault injection is restricted to offline isolated fixtures")
    dataset = args.dataset or DATA / "reliability.jsonl"
    cases = select(read_jsonl(dataset), args)
    rows = []
    with tempfile.TemporaryDirectory(prefix="retrade-faults-") as temp:
        for case in cases:
            for repeat in range(args.repeats):
                s = settings_for(args, Path(temp) / f"{case['id']}-{repeat}")
                error = None
                checks = []
                try:
                    checks = await execute(case["id"], s)
                except Exception as exc:
                    error = type(exc).__name__
                rows.append(
                    {
                        **case,
                        "repeat": repeat,
                        "passed": not error and bool(checks) and all(x["passed"] for x in checks),
                        "assertions": checks,
                        "error": error,
                    }
                )
        meta = metadata(args, s, dataset)
    summary = success_summary(rows)
    summary["scope"] = (
        "Actual Graph/SQLite/ASGI; injected faults and mocked upstream HTTP. No Docker crash, network partition, Redis/Milvus/Postgres integration claim."
    )
    return {"meta": meta, "summary": summary, "rows": rows}
