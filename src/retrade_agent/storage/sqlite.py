"""本地持久化仓储，短事务在事件循环之外执行。

此处只保存应用记录；LangGraph 独立管理 checkpoints.sqlite。JSON 记录使
PostgreSQL 端口可直接采用 JSONB 和相同 DTO 实现。
"""
import asyncio
import json
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from retrade_agent.errors import Conflict, NotFound


def dumps(value):
    """以稳定 JSON 格式序列化仓库记录。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def utcnow():
    """返回当前 UTC ISO 时间字符串。"""
    return datetime.now(timezone.utc).isoformat()


class SqliteRepository:
    """SQLite 业务仓库实现，使用短事务在线程池中执行阻塞数据库操作。"""

    def __init__(self, path: Path):
        """初始化实例依赖和内部状态。"""
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        """创建带外键和忙等待配置的 SQLite 连接。"""
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=15000")
        return c

    async def _call(self, fn):
        """在线程池中执行阻塞 SQLite 事务。"""

        def closed_run():
            """打开连接、执行事务并确保连接关闭。"""
            c = self._connect()
            try:
                with c:
                    return fn(c)
            finally:
                c.close()

        return await asyncio.to_thread(closed_run)

    async def setup(self, seed_orders: list[dict]):
        """初始化仓库结构并写入种子订单。"""

        def migrate(c):
            """创建或迁移 SQLite 表结构，并写入种子订单。"""
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    bucket TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
                    PRIMARY KEY(bucket,id));
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
                    content TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS ix_messages_session ON messages(session_id,created_at);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL, response TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS ix_runs_session ON runs(session_id,created_at);
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS traces (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL,
                    session_id TEXT NOT NULL, event TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS ix_trace_request ON traces(request_id,seq);
                CREATE TABLE IF NOT EXISTS leases (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
            """
            )
            for item in seed_orders:
                item = dict(item)
                days = item.pop("delivered_days_ago", None)
                item["delivered_at"] = (
                    (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                    if days is not None
                    else None
                )
                c.execute(
                    "INSERT OR IGNORE INTO entities VALUES(?,?,?,?,?)",
                    ("order", item["order_id"], dumps(item), 1, utcnow()),
                )

        await self._call(migrate)

    async def _get(self, bucket, key):
        """按 bucket 和 key 读取一条实体记录。"""

        def query(c):
            """执行单条实体查询并处理不存在情况。"""
            row = c.execute(
                "SELECT data,version FROM entities WHERE bucket=? AND id=?", (bucket, key)
            ).fetchone()
            if not row:
                raise NotFound("记录不存在")
            return {**json.loads(row["data"]), "version": row["version"]}

        return await self._call(query)

    async def _list(self, bucket):
        """按更新时间倒序列出指定 bucket 的实体记录。"""
        return await self._call(
            lambda c: [
                {**json.loads(r["data"]), "version": r["version"]}
                for r in c.execute(
                    "SELECT data,version FROM entities WHERE bucket=? ORDER BY updated_at DESC", (bucket,)
                )
            ]
        )

    async def _put(self, bucket, key, value, only_new=False):
        """插入或更新一条实体记录。"""

        def write(c):
            """执行实体 upsert 的 SQLite 写事务。"""
            if only_new:
                c.execute(
                    "INSERT OR IGNORE INTO entities VALUES(?,?,?,?,?)",
                    (bucket, key, dumps(value), 1, utcnow()),
                )
            else:
                c.execute(
                    """INSERT INTO entities VALUES(?,?,?,?,?) ON CONFLICT(bucket,id)
                    DO UPDATE SET data=excluded.data,version=entities.version+1,updated_at=excluded.updated_at""",
                    (bucket, key, dumps(value), 1, utcnow()),
                )
            row = c.execute(
                "SELECT data,version FROM entities WHERE bucket=? AND id=?", (bucket, key)
            ).fetchone()
            return {**json.loads(row["data"]), "version": row["version"]}

        return await self._call(write)

    async def _mutate(self, bucket, key, updates, expected_version=None):
        """读取、版本校验并局部更新一条实体记录。"""

        def update(c):
            """执行带版本校验的 SQLite 更新事务。"""
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT data,version FROM entities WHERE bucket=? AND id=?", (bucket, key)
            ).fetchone()
            if not row:
                raise NotFound("记录不存在")
            if expected_version is not None and row["version"] != expected_version:
                raise Conflict("数据已更新，请刷新后重试")
            value = {**json.loads(row["data"]), **updates, "updated_at": utcnow()}
            version = row["version"] + 1
            c.execute(
                "UPDATE entities SET data=?,version=?,updated_at=? WHERE bucket=? AND id=?",
                (dumps(value), version, utcnow(), bucket, key),
            )
            return {**value, "version": version}

        return await self._call(update)

    async def create_session(self, session_id, customer_id):
        """创建当前客户的新聊天会话。"""
        return await self._put(
            "session",
            session_id,
            {
                "session_id": session_id,
                "customer_id": customer_id,
                "active_domain": None,
                "status": "active",
                "title": "新会话",
                "created_at": utcnow(),
                "updated_at": utcnow(),
            },
            True,
        )

    async def get_session(self, session_id):
        """读取会话记录。"""
        return await self._get("session", session_id)

    async def list_sessions(self, customer_id):
        """列出指定客户的会话记录。"""
        return [s for s in await self._list("session") if s["customer_id"] == customer_id][:100]

    async def update_session(self, session_id, **fields):
        """更新会话字段。"""
        await self._mutate("session", session_id, fields)

    async def add_message(self, session_id, message_id, role, content):
        """写入一条会话消息。"""

        def insert(c):
            """执行 SQLite 插入或幂等读取事务。"""
            c.execute(
                "INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?)",
                (message_id, session_id, role, content, utcnow()),
            )

        await self._call(insert)

    async def messages(self, session_id, limit=100):
        """按时间顺序读取会话消息。"""
        limit = max(1, min(limit, 500))
        return await self._call(
            lambda c: [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM (SELECT rowid,* FROM messages WHERE session_id=? ORDER BY rowid DESC LIMIT ?) ORDER BY rowid",
                    (session_id, limit),
                )
            ]
        )

    async def begin_run(self, request_id, session_id, fingerprint):
        """登记或复用一次幂等请求运行记录。"""

        def begin(c):
            """begin 函数，封装该模块中的一段独立处理逻辑。"""
            c.execute(
                "INSERT OR IGNORE INTO runs VALUES(?,?,?,?,?,?,?)",
                (request_id, session_id, fingerprint, "processing", None, utcnow(), utcnow()),
            )
            row = dict(c.execute("SELECT * FROM runs WHERE id=?", (request_id,)).fetchone())
            if row["session_id"] != session_id or row["fingerprint"] != fingerprint:
                raise Conflict("同一 request_id 不能用于不同请求")
            row["response"] = json.loads(row["response"]) if row["response"] else None
            return row

        return await self._call(begin)

    async def finish_run(self, request_id, response, status="done"):
        """保存运行最终响应和状态。"""
        await self._call(
            lambda c: c.execute(
                "UPDATE runs SET status=?,response=?,updated_at=? WHERE id=?",
                (status, dumps(response), utcnow(), request_id),
            ).rowcount
        )

    async def get_run(self, request_id):
        """读取指定请求的运行记录。"""

        def get(c):
            """执行 SQLite 查询并转换为 Python 数据结构。"""
            r = c.execute("SELECT * FROM runs WHERE id=?", (request_id,)).fetchone()
            if not r:
                return None
            v = dict(r)
            v["response"] = json.loads(v["response"]) if v["response"] else None
            return v

        return await self._call(get)

    async def create_ticket(self, ticket):
        """保存新建人工工单。"""
        return await self._put("ticket", ticket["ticket_id"], ticket, True)

    async def get_ticket(self, ticket_id):
        """读取人工工单。"""
        return await self._get("ticket", ticket_id)

    async def list_tickets(self, status=None):
        """按状态列出人工工单。"""
        values = await self._list("ticket")
        return [t for t in values if not status or t["status"] == status][:200]

    async def save_ticket(self, ticket_id, updates, expected_version=None):
        """更新人工工单并进行可选版本校验。"""
        return await self._mutate("ticket", ticket_id, updates, expected_version)

    async def save_case(self, case):
        """保存售后 case 的最新状态。"""
        return await self._put("case", case["case_id"], case)

    async def get_case(self, case_id):
        """读取售后 case。"""
        return await self._get("case", case_id)

    async def operation(self, key, fingerprint, result):
        """用幂等键保存或读取业务操作结果。"""

        def insert(c):
            """执行 SQLite 插入或幂等读取事务。"""
            c.execute("INSERT OR IGNORE INTO operations VALUES(?,?,?)", (key, fingerprint, dumps(result)))
            row = c.execute("SELECT * FROM operations WHERE id=?", (key,)).fetchone()
            if row["fingerprint"] != fingerprint:
                raise Conflict("幂等键对应的业务参数发生变化")
            return json.loads(row["result"])

        return await self._call(insert)

    async def get_orders(self):
        """读取所有模拟订单。"""
        return await self._list("order")

    async def knowledge(self):
        """读取所有知识文档记录。"""
        return await self._list("document")

    async def put_document(self, document):
        """保存知识文档记录。"""
        await self._put("document", document["document_id"], {**document, "updated_at": utcnow()})

    async def delete_document(self, document_id):
        """删除知识文档记录。"""
        await self._call(
            lambda c: c.execute(
                "DELETE FROM entities WHERE bucket=? AND id=?", ("document", document_id)
            ).rowcount
        )

    async def append_trace(self, request_id, session_id, event):
        """追加一次请求追踪事件。"""
        await self._call(
            lambda c: c.execute(
                "INSERT INTO traces(request_id,session_id,event,created_at) VALUES(?,?,?,?)",
                (request_id, session_id, dumps(event), utcnow()),
            ).rowcount
        )

    async def traces(self, request_id, limit=300):
        """查询指定 request_id 的执行追踪事件。"""
        return await self._call(
            lambda c: [
                json.loads(r["event"])
                for r in c.execute(
                    "SELECT event FROM traces WHERE request_id=? ORDER BY seq LIMIT ?",
                    (request_id, min(limit, 500)),
                )
            ]
        )

    async def stats(self):
        """统计仓库中的主要业务记录数量。"""

        def get(c):
            """执行 SQLite 查询并转换为 Python 数据结构。"""
            counts = {
                r["bucket"]: r["n"]
                for r in c.execute("SELECT bucket,COUNT(*) n FROM entities GROUP BY bucket")
            }
            counts.update(
                sessions=counts.get("session", 0),
                tickets=counts.get("ticket", 0),
                cases=counts.get("case", 0),
                documents=counts.get("document", 0),
            )
            counts["runs"] = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            counts["completed_runs"] = c.execute("SELECT COUNT(*) FROM runs WHERE status='done'").fetchone()[
                0
            ]
            return counts

        return await self._call(get)

    @asynccontextmanager
    async def lease(self, session_id, ttl=240):
        """限制本地进程间每个会话仅有一个活动任务，且请求时限小于租约有效期。"""
        owner = str(uuid.uuid4())

        def acquire(c):
            """尝试获取或续写当前会话的租约记录。"""
            cur = c.execute(
                """INSERT INTO leases VALUES(?,?,?) ON CONFLICT(id)
                DO UPDATE SET owner=excluded.owner,expires=excluded.expires WHERE leases.expires < ?""",
                (session_id, owner, time.time() + ttl, time.time()),
            )
            return cur.rowcount == 1

        if not await self._call(acquire):
            raise Conflict("该会话正在处理中，请等待当前请求结束")
        try:
            yield
        finally:
            await self._call(
                lambda c: c.execute("DELETE FROM leases WHERE id=? AND owner=?", (session_id, owner)).rowcount
            )
