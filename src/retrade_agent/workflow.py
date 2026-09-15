"""Use-case facade shared by JSON and SSE APIs. No second chat execution path.
Requests and resumes are serialized per session; receipts are durable and idempotent.
"""
import asyncio
import hashlib
import time
import uuid
from langgraph.types import Command
from retrade_agent.errors import AppError, Conflict
from retrade_agent.models import ChatResult


def public_case(case):
    """过滤售后 case 中可对外返回的安全字段。"""
    if not case:
        return None
    allowed = (
        "case_id",
        "order_id",
        "product",
        "amount_cents",
        "issue_type",
        "reason",
        "status",
        "risk_level",
        "customer_confirmed",
        "policy",
        "result",
        "ticket_id",
    )
    return {k: case[k] for k in allowed if k in case}


def collect_interrupts(snapshot):
    """递归收集 LangGraph 快照中的暂停点。"""
    found = []
    for task in getattr(snapshot, "tasks", ()) or ():
        found.extend(getattr(task, "interrupts", ()) or ())
        nested = getattr(task, "state", None)
        if hasattr(nested, "tasks"):
            found.extend(collect_interrupts(nested))
    return found


class WorkflowService:
    """工作流门面服务，统一 API 与 LangGraph 之间的请求生命周期。"""

    def __init__(self, container, graph):
        """初始化实例依赖和内部状态。"""
        self.c = container
        self.graph = graph

    async def authorize_session(self, actor, session_id):
        """校验当前访问者是否拥有指定会话。"""
        s = await self.c.repo.get_session(session_id)
        self.c.permission.require_owner(actor, s["customer_id"])
        return s

    @staticmethod
    def config(session_id):
        """生成 LangGraph 会话级运行配置。"""
        return {"configurable": {"thread_id": session_id}, "recursion_limit": 80}

    async def _drive(self, input_value, session_id, request_id, start):
        """驱动图执行并持续产出阶段事件或最终结果。"""
        config = self.config(session_id)
        interrupts = []
        async for item in self.graph.astream(
            input_value, config=config, stream_mode=["updates", "custom"], subgraphs=True
        ):
            if len(item) == 3:
                namespace, mode, data = item
            else:
                mode, data = item
                namespace = ()
            event = None
            if mode == "custom" and isinstance(data, dict):
                event = data
            elif mode == "updates" and isinstance(data, dict):
                if "__interrupt__" in data:
                    interrupts.extend(data["__interrupt__"])
                names = [k for k in data if not k.startswith("__")]
                if names:
                    event = {
                        "type": "stage",
                        "stage": names[-1],
                        "message": "节点完成",
                        "namespace": list(namespace),
                    }
            if event:
                safe = {
                    **event,
                    "request_id": request_id,
                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
                }
                await self.c.repo.append_trace(request_id, session_id, safe)
                yield safe
        snapshot = await self.graph.aget_state(config, subgraphs=True)
        interrupts.extend(collect_interrupts(snapshot))
        value = dict(snapshot.values or {})
        pending = next(
            (i.value for i in interrupts if isinstance(i.value, dict) and i.value.get("ticket_id")), None
        )
        if pending:
            ticket = await self.c.repo.get_ticket(pending["ticket_id"])
            case = None
            if ticket["data"].get("case_id"):
                case = await self.c.repo.get_case(ticket["data"]["case_id"])
            result = ChatResult(
                reply="已进入人工审核，等待客服处理。可继续补充说明。"
                if ticket["kind"] == "approval"
                else "已为你转接人工客服，等待期间可以继续补充信息。",
                session_id=session_id,
                request_id=request_id,
                domain="after_sales" if case else "human",
                active_domain="human",
                intent="after_sale_rule" if case else "human",
                status="waiting_human",
                waiting_human=True,
                ticket_id=ticket["ticket_id"],
                case=public_case(case),
                used_tools=value.get("used_tools", []),
                simulated=self.c.settings.app_mode == "offline",
                total_ms=round((time.perf_counter() - start) * 1000, 1),
            )
            yield {"type": "human_wait", "ticket_id": ticket["ticket_id"], "kind": ticket["kind"]}
        else:
            result = self._result(value, session_id, request_id, start)
        yield {"type": "result", "result": result.model_dump()}

    def _result(self, value, session_id, request_id, start):
        """将图状态转换为统一聊天结果。"""
        return ChatResult(
            reply=value.get("final_answer") or "当前没有可显示的回复。",
            session_id=session_id,
            request_id=request_id,
            domain=value.get("result_domain", "customer"),
            active_domain=value.get("active_domain") or "customer",
            intent=value.get("intent", "chat"),
            sources=value.get("sources", []),
            used_tools=value.get("used_tools", []),
            status=value.get("status", "responded"),
            case=public_case(value.get("after_sales_case")),
            retrieval_detail=value.get("retrieval_detail", {}),
            token_usage=value.get("token_usage", {}),
            total_ms=round((time.perf_counter() - start) * 1000, 1),
            cache_hit=value.get("cache_hit", False),
            simulated=self.c.settings.app_mode == "offline"
            or value.get("result_domain") in ("order", "after_sales"),
        )

    async def _persist(self, result, message_id):
        """持久化助手回复、会话状态和运行结果。"""
        await self.c.repo.add_message(result["session_id"], message_id, "assistant", result["reply"])
        await self.c.repo.update_session(
            result["session_id"],
            active_domain=result["active_domain"],
            status=result["status"],
            last_result=result,
            ticket_id=result.get("ticket_id"),
        )
        await self.c.repo.finish_run(result["request_id"], result)

    async def events(self, actor, session_id, message, request_id):
        """Yield live operational events; release answer only after domain/evidence checks.
        The final token event is buffered, not falsely advertised as live model tokens.
        """
        start = time.perf_counter()
        repo = self.c.repo
        await self.authorize_session(actor, session_id)
        async with repo.lease(session_id, self.c.settings.max_request_seconds + 60):
            fingerprint = hashlib.sha256(
                (actor.customer_id + "|" + session_id + "|" + message).encode()
            ).hexdigest()
            run = await repo.begin_run(request_id, session_id, fingerprint)
            if run["status"] == "done" and run["response"]:
                yield {"type": "token", "content": run["response"]["reply"], "buffered": True}
                yield {"type": "done", **run["response"], "replayed": True}
                return
            await repo.add_message(session_id, "user:" + request_id, "user", message)
            s = await repo.get_session(session_id)
            if s["title"] == "新会话":
                await repo.update_session(session_id, title=message[:28])
            if s.get("status") == "waiting_human" and s.get("ticket_id"):
                # Additional customer messages are persisted but DO NOT resume AI/approval.
                last = s.get("last_result", {})
                result = {
                    **last,
                    "reply": "补充信息已记录，人工客服可以查看；当前仍在等待人工处理。",
                    "request_id": request_id,
                    "total_ms": round((time.perf_counter() - start) * 1000, 1),
                }
                await self._persist(result, "assistant:" + request_id)
                yield {"type": "human_wait", "ticket_id": s["ticket_id"]}
                yield {"type": "token", "content": result["reply"], "buffered": True}
                yield {"type": "done", **result}
                return
            try:
                async with asyncio.timeout(self.c.settings.max_request_seconds):
                    snapshot = await self.graph.aget_state(self.config(session_id))
                    previous = snapshot.values or {}
                    if (
                        previous.get("request_id") == request_id
                        and previous.get("final_answer")
                        and not snapshot.next
                    ):
                        result = self._result(previous, session_id, request_id, start).model_dump()
                    else:
                        history = await repo.messages(session_id, 24)
                        input_value = {
                            "session_id": session_id,
                            "request_id": request_id,
                            "customer_id": actor.customer_id,
                            "user_message": message,
                            "messages": [
                                {"id": m["id"], "role": m["role"], "content": m["content"]} for m in history
                            ],
                        }
                        # Same failed request resumes its pending nodes. A new request starts a new turn.
                        if previous.get("request_id") == request_id and snapshot.next:
                            input_value = None
                        result = None
                        async for event in self._drive(input_value, session_id, request_id, start):
                            if event["type"] == "result":
                                result = event["result"]
                            else:
                                yield event
                        if result is None:
                            raise RuntimeError("Graph did not return a result")
                await self._persist(result, "assistant:" + request_id)
                yield {"type": "token", "content": result["reply"], "buffered": True}
                yield {"type": "done", **result}
            except asyncio.CancelledError:
                # Cancellation never executes an automatic resume or a money retry.
                await repo.finish_run(request_id, {"error": "client_disconnected"}, "failed")
                raise
            except Exception as exc:
                await repo.finish_run(request_id, {"error_code": type(exc).__name__}, "failed")
                await repo.append_trace(request_id, session_id, {"type": "error", "code": type(exc).__name__})
                yield {
                    "type": "error",
                    "code": getattr(exc, "code", "EXECUTION_FAILED"),
                    "message": exc.message
                    if isinstance(exc, AppError)
                    else "处理未完成，可使用相同 request_id 重试；请勿重复发起售后操作。",
                    "request_id": request_id,
                }

    async def chat(self, actor, session_id, message, request_id):
        """执行普通 JSON 聊天请求并返回最终结果。"""
        final = None
        async for event in self.events(actor, session_id, message, request_id):
            if event["type"] == "done":
                final = {k: v for k, v in event.items() if k != "type"}
            if event["type"] == "error":
                raise AppError(event["message"])
        if final is None:
            raise AppError("未获得最终结果")
        return final

    async def resume(self, actor, ticket_id, decision, message, expected_version, request_id):
        """由人工决策恢复被暂停的图执行。"""
        self.c.permission.require_staff(actor)
        t = await self.c.repo.get_ticket(ticket_id)
        sid = t["session_id"]
        start = time.perf_counter()
        async with self.c.repo.lease(sid, self.c.settings.max_request_seconds + 60):
            t = await self.c.human.prepare_decision(actor, ticket_id, decision, message, expected_version)
            if t["status"] == "resolved":
                return t["receipt"]
            fingerprint = hashlib.sha256((ticket_id + "|" + decision + "|" + message).encode()).hexdigest()
            await self.c.repo.begin_run(request_id, sid, fingerprint)
            snapshot = await self.graph.aget_state(self.config(sid), subgraphs=True)
            pending = [i.value for i in collect_interrupts(snapshot) if isinstance(i.value, dict)]
            matching = any(p.get("ticket_id") == ticket_id for p in pending)
            if not matching:
                # Crash after graph completion but before receipt commit: reconcile, never execute twice.
                values = snapshot.values or {}
                case = values.get("after_sales_case") or {}
                completed = (
                    t["kind"] == "support"
                    and values.get("result_domain") == "human"
                    and values.get("request_id") == t["request_id"]
                )
                completed = completed or (
                    t["kind"] == "approval"
                    and case.get("case_id") == t["data"].get("case_id")
                    and case.get("status") in ("completed", "rejected")
                )
                if not completed:
                    raise Conflict("工单与当前暂停点不匹配，请检查会话状态")
                result = self._result(values, sid, request_id, start).model_dump()
            else:
                fingerprint = hashlib.sha256(
                    (ticket_id + "|" + decision + "|" + message).encode()
                ).hexdigest()
                await self.c.repo.begin_run(request_id, sid, fingerprint)
                result = None
                async with asyncio.timeout(self.c.settings.max_request_seconds):
                    async for event in self._drive(
                        Command(resume={"ticket_id": ticket_id, **t["decision"]}), sid, request_id, start
                    ):
                        if event["type"] == "result":
                            result = event["result"]
                if result is None:
                    raise AppError("恢复未产生结果")
                if result["waiting_human"]:
                    raise Conflict("仍有未处理的暂停点")
            await self._persist(result, "human:" + ticket_id)
            await self.c.human.complete(ticket_id, result)
            return result
