from types import SimpleNamespace
import uuid
import pytest
from evaluation.common import settings_for


def test_offline_isolation_ignores_ambient_production_settings(monkeypatch, tmp_path):
    for k, v in {
        "AIROBOT_MODE": "live",
        "AIROBOT_APP_MODE": "live",
        "AIROBOT_VECTOR_STORE": "milvus",
        "AIROBOT_DATA_DIR": "/unwanted",
        "AIROBOT_CACHE_ENABLED": "true",
        "AIROBOT_REDIS_URL": "redis://unwanted",
        "AIROBOT_STORAGE_BACKEND": "postgres",
    }.items():
        monkeypatch.setenv(k, v)
    s = settings_for(SimpleNamespace(mode="offline", allow_live=False, top_k=5), tmp_path)
    assert s.app_mode == "offline" and s.vector_store == "local"
    assert s.data_dir == tmp_path and not s.cache_enabled and not s.redis_url
    assert s.storage_backend == "sqlite" and s.checkpoint_backend == "sqlite"


def test_live_requires_explicit_opt_in(tmp_path):
    with pytest.raises(ValueError, match="allow-live"):
        settings_for(SimpleNamespace(mode="live", allow_live=False), tmp_path)


@pytest.mark.asyncio
async def test_callbacks_capture_only_actual_tool_contexts(tmp_path):
    from retrade_agent.bootstrap import build_container
    from retrade_agent.models import Actor
    from evaluation.observe import attach, chat

    s = settings_for(SimpleNamespace(mode="offline", allow_live=False, top_k=5), tmp_path)
    async with build_container(s) as c:
        attach(c)
        sid = str(uuid.uuid4())
        await c.repo.create_session(sid, "demo-customer")
        result, trace, error = await chat(
            c, Actor("demo-customer"), sid, "平台退货规则是什么？", str(uuid.uuid4())
        )
        assert not error and result["reply"]
        calls = [x for x in trace["tool_calls"] if x["name"] == "search_knowledge"]
        assert calls and calls[0]["args"]["query"]
        assert trace["contexts"] == calls[0]["payload"]["contexts"]
        other = str(uuid.uuid4())
        await c.repo.create_session(other, "demo-customer")
        _, empty, _ = await chat(c, Actor("demo-customer"), other, "你好", str(uuid.uuid4()))
        assert empty["contexts"] == [] and empty["tool_calls"] == []
