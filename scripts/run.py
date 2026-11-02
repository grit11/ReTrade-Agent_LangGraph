"""从任意工作目录启动服务：python scripts/run.py [--port 8000]。"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    try:
        import langchain  # noqa: F401 - 启动时提前检查核心依赖是否安装
        import langgraph  # noqa: F401
        import uvicorn
        from retrade_agent.config import Settings

        settings = Settings()
    except ImportError as exc:
        raise SystemExit('Missing dependency. Run: python -m pip install -e ".[dev]"\n' + str(exc))
    print(
        "ReTrade Agent: "
        + settings.app_mode
        + " | "
        + settings.storage_backend
        + " | orders/refunds=SIMULATED"
    )
    # Windows 下 psycopg 要求 Selector 循环，必须在 Uvicorn 创建事件循环之前设置。
    # loop="none" 使新版 Uvicorn 也遵循该策略，避免显式创建 Proactor 循环。
    postgres_on_windows = sys.platform == "win32" and "postgres" in (
        settings.storage_backend, settings.checkpoint_backend
    )
    if postgres_on_windows:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run(
        "retrade_agent.api.app:app",
        host=args.host or settings.app_host,
        port=args.port or settings.app_port,
        reload=args.reload,
        workers=1,
        loop="none" if postgres_on_windows else "auto",
    )
