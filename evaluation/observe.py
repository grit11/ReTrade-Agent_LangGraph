"""Trace actual tool content and arguments via callbacks; never re-retrieve evidence."""

import json
import time
from contextvars import ContextVar
from langchain_core.callbacks import AsyncCallbackHandler

ACTIVE = ContextVar("evaluation_record", default=None)


class Recorder:
    def __init__(self):
        self.calls = []
        self.models = []
        self.events = []
        self.started = time.perf_counter()

    def elapsed(self):
        return (time.perf_counter() - self.started) * 1000

    def contexts(self):
        contexts = []
        for c in self.calls:
            if c["name"] == "search_knowledge" and c.get("status") == "completed":
                payload = c.get("payload") or {}
                if payload.get("ok"):
                    contexts.extend(payload.get("contexts", []))
        return list(dict.fromkeys(contexts))

    def export(self):
        return {
            "tool_calls": self.calls,
            "model_calls": self.models,
            "events": self.events,
            "contexts": self.contexts(),
            "latency_ms": self.elapsed(),
            "token_usage_scope": "observed model callbacks only; null usage means unavailable",
        }


class AuditCallback(AsyncCallbackHandler):
    async def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kwargs):
        r = ACTIVE.get()
        if r is None:
            return
        args = inputs
        if args is None:
            try:
                args = json.loads(input_str)
            except (ValueError, TypeError):
                args = {"raw": input_str}
        if not isinstance(args, dict):
            args = {"value": args}
        args = {k: v for k, v in args.items() if k != "runtime"}
        r.calls.append(
            {
                "call_id": str(run_id),
                "name": (serialized or {}).get("name", "unknown"),
                "args": args,
                "status": "started",
                "started_ms": r.elapsed(),
            }
        )

    async def on_tool_end(self, output, *, run_id, **kwargs):
        r = ACTIVE.get()
        if r is None:
            return
        row = next((c for c in r.calls if c["call_id"] == str(run_id)), None)
        if row is None:
            return
        content = getattr(output, "content", output)
        try:
            payload = json.loads(content) if isinstance(content, str) else content
        except ValueError:
            payload = {"text": content}
        row.update(
            status="completed",
            ended_ms=r.elapsed(),
            payload=payload,
            artifact=getattr(output, "artifact", None),
        )

    async def on_tool_error(self, error, *, run_id, **kwargs):
        r = ACTIVE.get()
        if r:
            row = next((c for c in r.calls if c["call_id"] == str(run_id)), None)
            if row is not None:
                row.update(status="error", error=type(error).__name__, ended_ms=r.elapsed())

    async def on_llm_end(self, response, *, run_id, **kwargs):
        r = ACTIVE.get()
        if r is None:
            return
        usage = None
        for group in response.generations:
            for gen in group:
                found = getattr(getattr(gen, "message", None), "usage_metadata", None)
                if found:
                    usage = {k: found.get(k) for k in ["input_tokens", "output_tokens", "total_tokens"]}
        r.models.append({"call_id": str(run_id), "usage": usage, "ended_ms": r.elapsed()})


class ObservedGraph:
    def __init__(self, graph):
        self.graph = graph

    def __getattr__(self, key):
        return getattr(self.graph, key)

    async def astream(self, *args, **kwargs):
        config = dict(kwargs.pop("config", None) or {})
        config["callbacks"] = [AuditCallback()]
        async for event in self.graph.astream(*args, config=config, **kwargs):
            yield event


def attach(container):
    if not isinstance(container.workflow.graph, ObservedGraph):
        container.workflow.graph = ObservedGraph(container.workflow.graph)


async def chat(container, actor, sid, message, rid):
    recorder = Recorder()
    token = ACTIVE.set(recorder)
    final = None
    error = None
    try:
        async for event in container.workflow.events(actor, sid, message, rid):
            if event.get("type") == "done":
                final = {k: v for k, v in event.items() if k != "type"}
            elif event.get("type") == "error":
                error = event.get("code", "EXECUTION_FAILED")
            if event.get("type") not in ("token", "done"):
                recorder.events.append(event)
    except Exception as exc:
        error = type(exc).__name__
    finally:
        ACTIVE.reset(token)
    return final or {}, recorder.export(), error


async def resume(container, actor, ticket, decision, message, rid):
    recorder = Recorder()
    token = ACTIVE.set(recorder)
    error = None
    final = {}
    try:
        final = await container.workflow.resume(
            actor, ticket["ticket_id"], decision, message, ticket["version"], rid
        )
    except Exception as exc:
        error = type(exc).__name__
    finally:
        ACTIVE.reset(token)
    return final, recorder.export(), error
