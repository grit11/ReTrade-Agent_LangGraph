from __future__ import annotations
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).resolve().parent / "data"


def read_jsonl(path):
    rows = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if line.strip():
            try:
                row = json.loads(line)
            except ValueError as e:
                raise ValueError(f"{path}:{n}: invalid JSON") from e
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{n}: expected object")
            rows.append(row)
    return rows


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ratio(n, d):
    return {"numerator": n, "denominator": d, "value": n / d if d else None}


def mean(values):
    values = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return sum(values) / len(values) if values else None


def percentile(values, q):
    values = sorted(float(v) for v in values if v is not None)
    if not values:
        return None
    i = (len(values) - 1) * q
    a, b = math.floor(i), math.ceil(i)
    return values[a] + (values[b] - values[a]) * (i - a)


def latency(values):
    return {
        "n": len(values),
        "p50_ms": percentile(values, 0.5),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "mean_ms": mean(values),
    }


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def source_fingerprint():
    files = sorted((ROOT / "src/retrade_agent").rglob("*.py"))
    h = hashlib.sha256()
    for p in files:
        h.update(str(p.relative_to(ROOT)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def suite_fingerprint():
    h = hashlib.sha256()
    for p in sorted((ROOT / "evaluation").rglob("*.py")):
        h.update(str(p.relative_to(ROOT)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def metadata(args, settings=None, dataset=None):
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    versions = {}
    for pkg in ["langchain", "langgraph", "langchain-core", "ragas", "httpx"]:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            versions[pkg] = None
    info = {
        "suite_version": "1.0.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "suite": args.command,
        "mode": getattr(args, "mode", None),
        "commit": commit,
        "source_sha256": source_fingerprint(),
        "evaluation_sha256": suite_fingerprint(),
        "python": platform.python_version(),
        "packages": versions,
        "orders_and_refunds": "SIMULATED",
        "dataset_sha256": digest(dataset) if dataset else None,
        "dataset": Path(dataset).name if dataset else None,
        "repeats": getattr(args, "repeats", 1),
        "split": getattr(args, "split", "all"),
    }
    if settings is not None:
        info["config"] = {
            k: getattr(settings, k)
            for k in [
                "app_mode",
                "llm_model",
                "llm_temperature",
                "embedding_model",
                "rerank_enabled",
                "rerank_model",
                "vector_store",
                "top_k",
                "vector_k",
                "bm25_k",
                "fusion_k",
                "chunk_size",
                "chunk_overlap",
                "cache_enabled",
                "max_agent_steps",
                "max_handoffs",
                "structured_method",
                "llm_timeout",
                "max_request_seconds",
                "storage_backend",
                "checkpoint_backend",
            ]
        }
        from urllib.parse import urlsplit

        info["provider_hosts"] = {
            k: urlsplit(getattr(settings, k)).hostname
            for k in ["llm_base_url", "embedding_base_url", "rerank_base_url"]
        }
        info["llm_extra_body_sha256"] = hashlib.sha256(settings.llm_extra_body.encode()).hexdigest()
    kb = ROOT / "resources/knowledge/knowledge_base.txt"
    if kb.exists():
        info["knowledge_sha256"] = digest(kb)
    return info


def settings_for(args, data_dir):
    from retrade_agent.config import Settings
    from dotenv import dotenv_values

    if args.mode == "live" and not args.allow_live:
        raise ValueError("live calls require --allow-live")
    # Load explicitly, not via ambient app DB/cache/backend variables.
    values = (
        dict(dotenv_values(ROOT / ".env", encoding="utf-8-sig", interpolate=False))
        if args.mode == "live"
        else {}
    )
    if args.mode == "live":
        values.update(
            {k: v for k, v in os.environ.items() if k.startswith("AIROBOT_") or k == "SILICONFLOW_API_KEY"}
        )
    names = [
        "llm_base_url",
        "llm_model",
        "llm_api_key",
        "llm_temperature",
        "llm_timeout",
        "llm_extra_body",
        "structured_method",
        "embedding_base_url",
        "embedding_model",
        "embedding_api_key",
        "rerank_enabled",
        "rerank_model",
        "rerank_api_key",
        "rerank_base_url",
        "rerank_timeout",
        "siliconflow_api_key",
        "chunk_size",
        "chunk_overlap",
        "top_k",
        "vector_k",
        "bm25_k",
        "fusion_k",
        "max_agent_steps",
        "max_handoffs",
    ]
    explicit = {}
    for name in names:
        field = Settings.model_fields[name]
        alias = field.validation_alias
        aliases = alias.choices if hasattr(alias, "choices") else [alias or name.upper()]
        for a in aliases:
            if a in values and values[a] is not None:
                explicit[name] = values[a]
                break
    if getattr(args, "top_k", None):
        explicit["top_k"] = args.top_k
    # Pass every field explicitly: this prevents unrelated env vars from choosing live/remote storage.
    defaults = {name: field.get_default() for name, field in Settings.model_fields.items()}
    defaults.update(explicit)
    defaults.update(
        app_env="test",
        app_mode=args.mode,
        data_dir=Path(data_dir),
        storage_backend="sqlite",
        checkpoint_backend="sqlite",
        vector_store="local",
        redis_url="",
        async_database_url="",
        langgraph_database_url="",
        cache_enabled=False,
        milvus_reset=False,
        rate_limit_per_minute=100000,
        auth_secret="eval-only-signing-secret-not-for-production",
        admin_api_key="eval-only-admin",
        max_request_seconds=60 if args.mode == "offline" else 180,
    )
    return Settings(_env_file=None, **defaults)


def select(rows, args):
    if args.split != "all":
        rows = [r for r in rows if r.get("split") == args.split]
    if getattr(args, "limit", 0):
        rows = rows[: args.limit]
    if not rows:
        raise ValueError("No cases selected")
    return rows


def write_report(report, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    safe = json_safe(report)
    path = out / (report["meta"]["suite"] + ".json")
    path.write_text(json.dumps(safe, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    with path.with_suffix(".jsonl").open("w", encoding="utf-8") as f:
        for row in safe.get("rows", []):
            f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    lines = [
        f"# {report['meta']['suite']} 测评报告",
        "",
        f"模式：{report['meta'].get('mode')}；生成时间：{report['meta']['created_at']}",
        "",
        "> offline 为脚本模型；所有订单/售后为模拟。此报告不自动等于生产验收通过。",
        "",
        "## 汇总",
        "",
        "```json",
        json.dumps(safe.get("summary", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## 失败/待人工检查样本",
        "",
    ]
    failures = [r for r in safe.get("rows", []) if r.get("passed") is False or r.get("error")]
    lines += [
        f"- {r.get('id')}: {r.get('error') or r.get('failures') or r.get('assertions')}" for r in failures
    ]
    if not failures:
        lines.append("未记录规则失败；未执行的 Judge/RAGAS 不计为通过。")
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(path), "summary": safe.get("summary")}, ensure_ascii=False, indent=2))
    return path
