from __future__ import annotations
import asyncio
import tempfile
import time
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from evaluation.common import DATA, metadata, settings_for, read_jsonl, select, ratio, mean, latency
from evaluation.metrics import evidence_metrics, text_checks, turn_checks, success_summary


async def count_operations(repo):
    return await repo._call(lambda conn: conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0])


async def retrieval(args):
    from retrade_agent.bootstrap import build_container

    dataset = args.dataset or DATA / "knowledge.jsonl"
    cases = select(read_jsonl(dataset), args)
    rows = []
    with tempfile.TemporaryDirectory(prefix="retrade-eval-") as temp:
        s = settings_for(args, temp)
        if args.no_rerank:
            s.rerank_enabled = False
        async with build_container(s) as c:
            retr = c.knowledge.retriever
            if c.knowledge.last_error:
                raise RuntimeError("Knowledge initialization failed: " + c.knowledge.last_error)
            for case in cases:
                for repeat in range(args.repeats):
                    for strategy in args.strategies:
                        started = time.perf_counter()
                        error = None
                        contexts = []
                        sources = []
                        detail = {}
                        try:
                            if strategy == "hybrid":
                                result = await c.knowledge.search(case["question"])
                                contexts = result.contexts
                                sources = result.sources
                                detail = result.detail
                            elif strategy == "bm25":
                                found = retr.bm25.search(case["question"], s.top_k)
                                cs = [retr.chunks[i] for i, _ in found]
                                contexts = [x.text for x in cs]
                                sources = [x.source for x in cs]
                            else:
                                query = (await retr.embeddings.embed([case["question"]]))[0]
                                found = await retr.vectors.search(query, s.top_k, retr.generation)
                                by_id = {x.chunk_id: x for x in retr.chunks}
                                cs = [by_id[i] for i, _ in found if i in by_id]
                                contexts = [x.text for x in cs]
                                sources = [x.source for x in cs]
                        except Exception as exc:
                            error = type(exc).__name__
                        scores = (
                            {
                                str(k): evidence_metrics(contexts, case["gold_evidence"], k)
                                for k in args.ks
                                if k <= s.top_k
                            }
                            if case["answerable"]
                            else {}
                        )
                        rows.append(
                            {
                                "id": case["id"],
                                "repeat": repeat,
                                "strategy": strategy,
                                "category": case["category"],
                                "question": case["question"],
                                "reference": case["reference"],
                                "answerable": case["answerable"],
                                "split": case["split"],
                                "contexts": contexts,
                                "sources": sources,
                                "detail": detail,
                                "metrics_at_k": scores,
                                "error": error,
                                "latency_ms": (time.perf_counter() - started) * 1000,
                                "keyword_proxy_hit": any(
                                    k in "\n".join(contexts) for k in case.get("keywords", [])
                                ),
                                "returned_evidence_for_unanswerable": bool(contexts)
                                if not case["answerable"]
                                else None,
                            }
                        )
            meta = metadata(args, s, dataset)
            meta["chunk_count"] = len(retr.chunks)
            meta["strategies"] = args.strategies
            meta["ks"] = args.ks
    summary = {}
    for strategy in args.strategies:
        group = [r for r in rows if r["strategy"] == strategy]
        known = [r for r in group if r["answerable"]]
        unknown = [r for r in group if not r["answerable"]]
        at_k = {}
        for k in args.ks:
            values = [r["metrics_at_k"][str(k)] for r in known if str(k) in r["metrics_at_k"]]
            at_k[str(k)] = {
                "n": len(values),
                **{
                    m: mean([v[m] for v in values])
                    for m in ["evidence_hit", "evidence_unit_recall", "annotated_chunk_precision", "mrr"]
                },
            }
        summary[strategy] = {
            "n": len(group),
            "known_n": len(known),
            "unknown_n": len(unknown),
            "metrics": at_k,
            "errors": sum(bool(r["error"]) for r in group),
            "keyword_proxy_hit_known": ratio(sum(r["keyword_proxy_hit"] for r in known), len(known)),
            "unknown_nonempty_retrieval": ratio(
                sum(r["returned_evidence_for_unanswerable"] for r in unknown), len(unknown)
            ),
            "degraded_queries": sum(bool(r["detail"].get("degraded")) for r in group),
            "rerank_applied": sum(bool(r["detail"].get("rerank", {}).get("applied")) for r in group),
            "latency": latency([r["latency_ms"] for r in group]),
        }
    summary["interpretation"] = (
        "Evidence-unit labels are substring-based annotation proxies. Unknown nonempty retrieval is diagnostic, NOT hallucination rate. Local vector index only."
    )
    return {"meta": meta, "summary": summary, "rows": rows}


async def answers(args):
    from retrade_agent.bootstrap import build_container
    from retrade_agent.models import Actor
    from evaluation.observe import attach, chat

    dataset = args.dataset or DATA / "knowledge.jsonl"
    cases = select(read_jsonl(dataset), args)
    rows = []
    with tempfile.TemporaryDirectory(prefix="retrade-eval-") as temp:
        s = settings_for(args, temp)
        async with build_container(s) as c:
            attach(c)
            if c.knowledge.last_error:
                raise RuntimeError("Knowledge initialization failed: " + c.knowledge.last_error)
            for case in cases:
                for repeat in range(args.repeats):
                    sid = str(uuid.uuid4())
                    rid = str(uuid.uuid4())
                    actor = Actor("demo-customer")
                    await c.repo.create_session(sid, actor.customer_id)
                    result, trace, error = await chat(c, actor, sid, case["question"], rid)
                    if result.get("status") == "failed" and not error:
                        error = "FAILED_RESULT"
                    expected = case.get("expected_domain")
                    turn = {
                        "expect": {"domain": expected},
                        "required_tools": case.get("required_tools", []),
                        "tool_args": case.get("tool_args", []),
                    }
                    if not case.get("answerable", True):
                        turn["expect"]["domain"] = ["customer", "human"]
                    if case.get("id") in ("o07", "o08", "o12"):
                        turn["expect"]["domain"] = ["order", "human"]
                    checks = turn_checks(turn, result, trace["tool_calls"], trace["events"])
                    tx = text_checks(case, result.get("reply", ""))
                    rows.append(
                        {
                            "id": case["id"],
                            "repeat": repeat,
                            "category": case["category"],
                            "split": case["split"],
                            "evaluation_domain": "knowledge" if "gold_evidence" in case else "order",
                            "question": case["question"],
                            "reference": case["reference"],
                            "rubric": case.get("rubric", ""),
                            "answerable": case["answerable"],
                            "answer": result.get("reply", ""),
                            "result": result,
                            **trace,
                            "text_checks": tx,
                            "assertions": checks,
                            "error": error,
                            "passed": not error
                            and all(x["passed"] for x in checks)
                            and not tx["forbidden_pattern_matches"],
                            "quality_status": "UNSCORED_SEMANTICS",
                            "judge": {"status": "not_requested"},
                            "ragas": {"status": "not_requested"},
                        }
                    )
            meta = metadata(args, s, dataset)
    summary = {
        "n": len(rows),
        "execution_success": ratio(sum(not r["error"] for r in rows), len(rows)),
        "routing_and_tool_rule_pass": ratio(sum(r["passed"] for r in rows), len(rows)),
        "fact_coverage_proxy_mean": mean([r["text_checks"]["fact_coverage_proxy"] for r in rows]),
        "forbidden_pattern_cases": sum(bool(r["text_checks"]["forbidden_pattern_matches"]) for r in rows),
        "unknown_cases": sum(not r["answerable"] for r in rows),
        "latency": latency([r["latency_ms"] for r in rows]),
        "judge": "not_requested; run score --judge",
        "ragas": "not_requested; run score --ragas",
        "quality_gate": "NOT_ASSESSED; rule/text proxies are not answer correctness",
    }
    summary["by_category"] = {
        category: {
            "n": len(group),
            "routing_and_tool_rule_pass": ratio(sum(r["passed"] for r in group), len(group)),
            "fact_coverage_proxy_mean": mean([r["text_checks"]["fact_coverage_proxy"] for r in group]),
        }
        for category in sorted({r["category"] for r in rows})
        for group in [[r for r in rows if r["category"] == category]]
    }
    return {"meta": meta, "summary": summary, "rows": rows}


async def workflow(args):
    from retrade_agent.bootstrap import build_container
    from retrade_agent.models import Actor
    from evaluation.observe import attach, chat, resume

    dataset = args.dataset or DATA / "workflows.jsonl"
    cases = select(read_jsonl(dataset), args)
    rows = []
    with tempfile.TemporaryDirectory(prefix="retrade-eval-") as temp:
        for case in cases:
            for repeat in range(args.repeats):
                s = settings_for(args, Path(temp) / f"{case['id']}-{repeat}")
                history = []
                failures = []
                error = None
                sid = str(uuid.uuid4())
                last_rid = None
                last_message = None
                tid = None
                stack = AsyncExitStack()
                try:
                    c = await stack.enter_async_context(build_container(s))
                    attach(c)
                    if c.knowledge.last_error:
                        raise RuntimeError("knowledge initialization failed")
                    for override in case.get("order_overrides", []):
                        original = next(
                            o for o in await c.repo.get_orders() if o["order_id"] == override["order_id"]
                        )
                        await c.repo._put("order", override["order_id"], {**original, **override})
                    await c.repo.create_session(sid, "demo-customer")
                    for index, turn in enumerate(case["turns"]):
                        action = turn["action"]
                        if action == "restart":
                            await stack.aclose()
                            stack = AsyncExitStack()
                            c = await stack.enter_async_context(build_container(s))
                            attach(c)
                            history.append({"action": "restart", "assertions": []})
                            continue
                        if action == "resume":
                            if not tid:
                                raise ValueError("Expected ticket missing")
                            ticket = await c.repo.get_ticket(tid)
                            result, trace, err = await resume(
                                c,
                                Actor("staff-local", "staff"),
                                ticket,
                                turn["decision"],
                                turn["message"],
                                str(uuid.uuid4()),
                            )
                        else:
                            if action == "repeat":
                                rid = last_rid
                                message = last_message
                            else:
                                rid = str(uuid.uuid4())
                                message = turn["message"]
                                last_rid = rid
                                last_message = message
                            result, trace, err = await chat(c, Actor("demo-customer"), sid, message, rid)
                        tid = result.get("ticket_id") or tid
                        checks = turn_checks(turn, result, trace["tool_calls"], trace["events"])
                        if "expect_operations" in turn:
                            n = await count_operations(c.repo)
                            checks.append(
                                {
                                    "name": "operations_count",
                                    "actual": n,
                                    "expected": turn["expect_operations"],
                                    "passed": n == turn["expect_operations"],
                                }
                            )
                        if err or result.get("status") == "failed":
                            checks.append(
                                {
                                    "name": "execution_success",
                                    "passed": False,
                                    "error": err or "FAILED_RESULT",
                                }
                            )
                        failures.extend({"turn": index + 1, **ck} for ck in checks if not ck["passed"])
                        history.append(
                            {
                                "turn": index + 1,
                                "action": action,
                                "input": turn.get("message"),
                                "result": result,
                                **trace,
                                "assertions": checks,
                                "error": err,
                            }
                        )
                except Exception as exc:
                    error = type(exc).__name__
                    failures.append({"name": "scenario_execution", "passed": False, "error": error})
                finally:
                    await stack.aclose()
                rows.append(
                    {
                        "id": case["id"],
                        "repeat": repeat,
                        "category": case["category"],
                        "risk": case["risk"],
                        "split": case["split"],
                        "passed": not failures,
                        "failures": failures,
                        "error": error,
                        "turns": history,
                    }
                )
        meta = metadata(args, s, dataset)
    summary = success_summary(rows)
    summary["interpretation"] = (
        "Scenario contract success with mock orders. Offline runs validate scripted trajectories, not live model quality."
    )
    return {"meta": meta, "summary": summary, "rows": rows}


async def load(args):
    from retrade_agent.bootstrap import build_container
    from retrade_agent.models import Actor
    from evaluation.observe import attach, chat

    rows = []
    with tempfile.TemporaryDirectory(prefix="retrade-load-") as temp:
        s = settings_for(args, temp)
        async with build_container(s) as c:
            attach(c)
            semaphore = asyncio.Semaphore(args.concurrency)

            async def one(i):
                async with semaphore:
                    sid = str(uuid.uuid4())
                    await c.repo.create_session(sid, "demo-customer")
                    result, trace, error = await chat(
                        c, Actor("demo-customer"), sid, args.message, str(uuid.uuid4())
                    )
                    return {
                        "id": f"load-{i}",
                        "latency_ms": trace["latency_ms"],
                        "error": error,
                        "passed": not error
                        and result.get("status") != "failed"
                        and bool(result.get("reply")),
                        "tool_calls": len(trace["tool_calls"]),
                        "domain": result.get("domain"),
                    }

            start = time.perf_counter()
            rows = await asyncio.gather(*(one(i) for i in range(args.requests)))
            elapsed = time.perf_counter() - start
            meta = metadata(args, s)
            meta.update(concurrency=args.concurrency, requests=args.requests, message=args.message)
    return {
        "meta": meta,
        "rows": rows,
        "summary": {
            "n": len(rows),
            "success": ratio(sum(r["passed"] for r in rows), len(rows)),
            "latency": latency([r["latency_ms"] for r in rows]),
            "wall_seconds": elapsed,
            "completed_requests_per_second": len(rows) / elapsed,
            "scope": "In-process WorkflowService, independent sessions; NOT HTTP/network load. No production capacity claim.",
        },
    }
