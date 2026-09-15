"""Run from any working directory: python scripts/run.py [--port 8000]."""
import argparse
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
        import langchain, langgraph, uvicorn
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
    uvicorn.run(
        "retrade_agent.api.app:app",
        host=args.host or settings.app_host,
        port=args.port or settings.app_port,
        reload=args.reload,
        workers=1,
    )
