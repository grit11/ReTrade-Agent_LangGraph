"""Real running service smoke test. Uses configured mode; live mode incurs provider calls."""
import argparse
import uuid
import httpx

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--allow-live", action="store_true")
    a = p.parse_args()
    with httpx.Client(base_url=a.url, timeout=240) as c:
        h = c.get("/health")
        h.raise_for_status()
        mode = h.json()["app_mode"]
        if mode == "live" and not a.allow_live:
            raise SystemExit("Live mode detected. Re-run --allow-live to authorize inference costs.")
        c.post("/api/v1/auth/demo", json={"user": "demo-customer"}).raise_for_status()
        s = c.post("/api/v1/sessions", json={})
        s.raise_for_status()
        sid = s.json()["session_id"]
        for message in ["你好", "查询订单202608090001的物流", "大概什么时候到？"]:
            r = c.post(
                "/api/v1/chat", json={"session_id": sid, "request_id": str(uuid.uuid4()), "message": message}
            )
            r.raise_for_status()
            v = r.json()
            assert v["reply"] and v["engine"] == "langgraph"
            print(v["domain"], v["used_tools"], v["reply"][:100])
    print("Smoke passed. This does not validate every live answer or deployment dependency.")
