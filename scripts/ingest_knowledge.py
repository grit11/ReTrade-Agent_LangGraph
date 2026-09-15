"""通过管理接口导入知识文档，要求服务已运行且不读取旧项目。"""
import argparse
import os
from pathlib import Path
import httpx

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("file", type=Path)
    p.add_argument("--url", default="http://127.0.0.1:8000")
    a = p.parse_args()
    key = os.getenv("ADMIN_API_KEY", "dev-admin-change-me")
    with a.file.open("rb") as f:
        r = httpx.post(
            a.url.rstrip("/") + "/api/v1/knowledge/ingest",
            headers={"X-Admin-Token": key},
            files={"file": (a.file.name, f)},
            timeout=180,
        )
    if not r.is_success:
        raise SystemExit("Ingest failed with status " + str(r.status_code))
    print(r.json())
