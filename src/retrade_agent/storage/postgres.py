"""PostgreSQL 业务仓储实现。

本适配器保存业务记录；LangGraph 检查点仍由 storage.checkpoint 中的
AsyncPostgresSaver 管理。上层服务只依赖 StoragePort，不感知数据库类型。
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from retrade_agent.errors import Conflict, ConfigurationError, NotFound


def utcnow():
    """返回当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def _dsn(settings):
    """读取 PostgreSQL 连接串并兼容 asyncpg 前缀。"""
    value = (
        settings.async_database_url.get_secret_value() or settings.langgraph_database_url.get_secret_value()
    )
    value = value.replace("postgresql+asyncpg://", "postgresql://", 1)
    if not value:
        raise ConfigurationError(
            "PostgreSQL 业务存储未配置 DSN，请设置 ASYNC_DATABASE_URL 或 LANGGRAPH_DATABASE_URL"
        )
    return value


class PostgresRepository:
    """基于 psycopg 异步连接池的业务仓库。"""

    def __init__(self, settings):
        """保存连接配置，并延迟到 open() 建立连接。"""
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool
        except ImportError as exc:
            raise ConfigurationError(
                'PostgreSQL 业务存储需要依赖，请执行：python -m pip install -e ".[postgres]"'
            ) from exc
        self._dict_row = dict_row
        self._pool_cls = AsyncConnectionPool
        self._dsn = _dsn(settings)
        self._pool = None

    async def open(self):
        """打开连接池并确认数据库可连接。"""
        self._pool = self._pool_cls(
            conninfo=self._dsn,
            min_size=1,
            max_size=10,
            open=False,
            kwargs={"row_factory": self._dict_row},
        )
        await self._pool.open()
        try:
            await self._pool.wait(timeout=10)
        except BaseException:
            await self.close()
            raise

    async def close(self):
        """关闭连接池。"""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _connection(self):
        """返回连接上下文，并检查仓库已完成初始化。"""
        if self._pool is None:
            raise RuntimeError("PostgresRepository 尚未打开")
        return self._pool.connection()

    @staticmethod
    def _entity(row):
        """把实体表行转换为服务层 DTO。"""
        return {**row["data"], "version": row["version"]}

    async def setup(self, seed_orders: list[dict]):
        """创建业务表和索引，并写入缺失的种子订单。"""
        from psycopg.types.json import Jsonb

        schema = """
        CREATE TABLE IF NOT EXISTS retrade_entities (
            bucket TEXT NOT NULL, id TEXT NOT NULL, data JSONB NOT NULL,
            version INTEGER NOT NULL DEFAULT 1, updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (bucket, id));
        CREATE TABLE IF NOT EXISTS retrade_messages (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
            content TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL);
        ALTER TABLE retrade_messages ADD COLUMN IF NOT EXISTS seq BIGSERIAL;
        CREATE INDEX IF NOT EXISTS ix_retrade_messages_session
            ON retrade_messages(session_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_retrade_messages_sequence
            ON retrade_messages(session_id, seq);
        CREATE TABLE IF NOT EXISTS retrade_runs (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
            status TEXT NOT NULL, response JSONB, created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_retrade_runs_session
            ON retrade_runs(session_id, created_at);
        CREATE TABLE IF NOT EXISTS retrade_operations (
            id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result JSONB NOT NULL);
        CREATE TABLE IF NOT EXISTS retrade_traces (
            seq BIGSERIAL PRIMARY KEY, request_id TEXT NOT NULL, session_id TEXT NOT NULL,
            event JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_retrade_traces_request
            ON retrade_traces(request_id, seq);
        CREATE TABLE IF NOT EXISTS retrade_leases (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL);
        """
        async with self._connection() as conn:
            # 将并行进程的初始化串行化，避免 CREATE TABLE / INDEX 竞争。
            await conn.execute("SELECT pg_advisory_xact_lock(742819305)")
            await conn.execute(schema)
            for original in seed_orders:
                item = dict(original)
                days = item.pop("delivered_days_ago", None)
                item["delivered_at"] = (
                    (utcnow() - timedelta(days=days)).isoformat() if days is not None else None
                )
                await conn.execute(
                    """INSERT INTO retrade_entities(bucket,id,data,version,updated_at)
                    VALUES(%s,%s,%s,1,%s) ON CONFLICT(bucket,id) DO NOTHING""",
                    ("order", item["order_id"], Jsonb(item), utcnow()),
                )

    async def _get(self, bucket, key):
        """读取一条实体记录。"""
        async with self._connection() as conn:
            cursor = await conn.execute(
                "SELECT data,version FROM retrade_entities WHERE bucket=%s AND id=%s",
                (bucket, key),
            )
            row = await cursor.fetchone()
        if not row:
            raise NotFound("记录不存在")
        return self._entity(row)

    async def _list(self, bucket):
        """读取一个实体分区。"""
        async with self._connection() as conn:
            cursor = await conn.execute(
                "SELECT data,version FROM retrade_entities WHERE bucket=%s ORDER BY updated_at DESC",
                (bucket,),
            )
            rows = await cursor.fetchall()
        return [self._entity(row) for row in rows]

    async def _put(self, bucket, key, value, only_new=False):
        """插入或更新 JSONB 实体。"""
        from psycopg.types.json import Jsonb

        now = utcnow()
        async with self._connection() as conn:
            if only_new:
                await conn.execute(
                    """INSERT INTO retrade_entities(bucket,id,data,version,updated_at)
                    VALUES(%s,%s,%s,1,%s) ON CONFLICT(bucket,id) DO NOTHING""",
                    (bucket, key, Jsonb(value), now),
                )
            else:
                await conn.execute(
                    """INSERT INTO retrade_entities(bucket,id,data,version,updated_at)
                    VALUES(%s,%s,%s,1,%s)
                    ON CONFLICT(bucket,id) DO UPDATE SET data=EXCLUDED.data,
                    version=retrade_entities.version+1,updated_at=EXCLUDED.updated_at""",
                    (bucket, key, Jsonb(value), now),
                )
            cursor = await conn.execute(
                "SELECT data,version FROM retrade_entities WHERE bucket=%s AND id=%s",
                (bucket, key),
            )
            row = await cursor.fetchone()
        return self._entity(row)

    async def _mutate(self, bucket, key, updates, expected_version=None):
        """在事务内锁定实体并执行版本校验更新。"""
        from psycopg.types.json import Jsonb

        async with self._connection() as conn:
            cursor = await conn.execute(
                "SELECT data,version FROM retrade_entities WHERE bucket=%s AND id=%s FOR UPDATE",
                (bucket, key),
            )
            row = await cursor.fetchone()
            if not row:
                raise NotFound("记录不存在")
            if expected_version is not None and row["version"] != expected_version:
                raise Conflict("数据已更新，请刷新后重试")
            value = {**row["data"], **updates, "updated_at": utcnow().isoformat()}
            version = row["version"] + 1
            await conn.execute(
                """UPDATE retrade_entities SET data=%s,version=%s,updated_at=%s
                WHERE bucket=%s AND id=%s""",
                (Jsonb(value), version, utcnow(), bucket, key),
            )
        return {**value, "version": version}

    async def create_session(self, session_id, customer_id):
        """创建聊天会话。"""
        return await self._put(
            "session",
            session_id,
            {
                "session_id": session_id,
                "customer_id": customer_id,
                "active_domain": None,
                "status": "active",
                "title": "新会话",
                "created_at": utcnow().isoformat(),
                "updated_at": utcnow().isoformat(),
            },
            True,
        )

    async def get_session(self, session_id):
        """读取聊天会话。"""
        return await self._get("session", session_id)

    async def list_sessions(self, customer_id):
        """列出当前客户会话。"""
        return [s for s in await self._list("session") if s["customer_id"] == customer_id][:100]

    async def update_session(self, session_id, **fields):
        """更新会话字段。"""
        await self._mutate("session", session_id, fields)

    async def add_message(self, session_id, message_id, role, content):
        """幂等写入会话消息。"""
        async with self._connection() as conn:
            await conn.execute(
                """INSERT INTO retrade_messages(id,session_id,role,content,created_at)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
                (message_id, session_id, role, content, utcnow()),
            )

    async def messages(self, session_id, limit=100):
        """按时间顺序读取会话消息。"""
        limit = max(1, min(limit, 500))
        async with self._connection() as conn:
            cursor = await conn.execute(
                """SELECT id,session_id,role,content,created_at FROM retrade_messages
                WHERE session_id=%s ORDER BY seq DESC LIMIT %s""",
                (session_id, limit),
            )
            rows = await cursor.fetchall()
        result = [dict(row) for row in reversed(rows)]
        for row in result:
            if hasattr(row.get("created_at"), "isoformat"):
                row["created_at"] = row["created_at"].isoformat()
        return result

    async def begin_run(self, request_id, session_id, fingerprint):
        """登记或复用幂等请求。"""
        now = utcnow()
        async with self._connection() as conn:
            await conn.execute(
                """INSERT INTO retrade_runs(id,session_id,fingerprint,status,response,created_at,updated_at)
                VALUES(%s,%s,%s,'processing',NULL,%s,%s) ON CONFLICT(id) DO NOTHING""",
                (request_id, session_id, fingerprint, now, now),
            )
            cursor = await conn.execute("SELECT * FROM retrade_runs WHERE id=%s", (request_id,))
            row = await cursor.fetchone()
        if row["session_id"] != session_id or row["fingerprint"] != fingerprint:
            raise Conflict("同一 request_id 不能用于不同请求")
        return dict(row)

    async def finish_run(self, request_id, response, status="done"):
        """保存运行结果。"""
        from psycopg.types.json import Jsonb

        async with self._connection() as conn:
            await conn.execute(
                "UPDATE retrade_runs SET status=%s,response=%s,updated_at=%s WHERE id=%s",
                (status, Jsonb(response), utcnow(), request_id),
            )

    async def get_run(self, request_id):
        """读取运行结果。"""
        async with self._connection() as conn:
            cursor = await conn.execute("SELECT * FROM retrade_runs WHERE id=%s", (request_id,))
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def create_ticket(self, ticket):
        """保存人工工单。"""
        return await self._put("ticket", ticket["ticket_id"], ticket, True)

    async def get_ticket(self, ticket_id):
        """读取人工工单。"""
        return await self._get("ticket", ticket_id)

    async def list_tickets(self, status=None):
        """按状态列出人工工单。"""
        values = await self._list("ticket")
        return [t for t in values if not status or t["status"] == status][:200]

    async def save_ticket(self, ticket_id, updates, expected_version=None):
        """更新人工工单并执行乐观锁校验。"""
        return await self._mutate("ticket", ticket_id, updates, expected_version)

    async def save_case(self, case):
        """保存售后 case。"""
        return await self._put("case", case["case_id"], case)

    async def get_case(self, case_id):
        """读取售后 case。"""
        return await self._get("case", case_id)

    async def operation(self, key, fingerprint, result):
        """保存或读取幂等业务操作结果。"""
        from psycopg.types.json import Jsonb

        async with self._connection() as conn:
            await conn.execute(
                """INSERT INTO retrade_operations(id,fingerprint,result) VALUES(%s,%s,%s)
                ON CONFLICT(id) DO NOTHING""",
                (key, fingerprint, Jsonb(result)),
            )
            cursor = await conn.execute(
                "SELECT fingerprint,result FROM retrade_operations WHERE id=%s", (key,)
            )
            row = await cursor.fetchone()
        if row["fingerprint"] != fingerprint:
            raise Conflict("幂等键对应的业务参数发生变化")
        return dict(row["result"])

    async def get_orders(self):
        """读取所有模拟订单。"""
        return await self._list("order")

    async def knowledge(self):
        """读取知识文档登记。"""
        return await self._list("document")

    async def put_document(self, document):
        """保存知识文档登记。"""
        await self._put("document", document["document_id"], {**document, "updated_at": utcnow().isoformat()})

    async def delete_document(self, document_id):
        """删除知识文档登记。"""
        async with self._connection() as conn:
            await conn.execute(
                "DELETE FROM retrade_entities WHERE bucket=%s AND id=%s", ("document", document_id)
            )

    async def append_trace(self, request_id, session_id, event):
        """追加执行追踪事件。"""
        from psycopg.types.json import Jsonb

        async with self._connection() as conn:
            await conn.execute(
                """INSERT INTO retrade_traces(request_id,session_id,event,created_at)
                VALUES(%s,%s,%s,%s)""",
                (request_id, session_id, Jsonb(event), utcnow()),
            )

    async def traces(self, request_id, limit=300):
        """读取执行追踪事件。"""
        async with self._connection() as conn:
            cursor = await conn.execute(
                "SELECT event FROM retrade_traces WHERE request_id=%s ORDER BY seq LIMIT %s",
                (request_id, min(limit, 500)),
            )
            rows = await cursor.fetchall()
        return [dict(row["event"]) for row in rows]

    async def stats(self):
        """统计业务记录数量。"""
        async with self._connection() as conn:
            cursor = await conn.execute("SELECT bucket,COUNT(*) AS n FROM retrade_entities GROUP BY bucket")
            counts = {row["bucket"]: row["n"] for row in await cursor.fetchall()}
            cursor = await conn.execute("SELECT COUNT(*) AS n FROM retrade_runs")
            counts["runs"] = (await cursor.fetchone())["n"]
            cursor = await conn.execute("SELECT COUNT(*) AS n FROM retrade_runs WHERE status='done'")
            counts["completed_runs"] = (await cursor.fetchone())["n"]
        counts.update(
            sessions=counts.get("session", 0),
            tickets=counts.get("ticket", 0),
            cases=counts.get("case", 0),
            documents=counts.get("document", 0),
        )
        return counts

    @asynccontextmanager
    async def lease(self, session_id, ttl=240):
        """使用 PostgreSQL 条件更新获取会话互斥租约。"""
        owner = str(uuid.uuid4())
        async with self._connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO retrade_leases(id,owner,expires_at) VALUES(%s,%s,%s)
                ON CONFLICT(id) DO UPDATE SET owner=EXCLUDED.owner,expires_at=EXCLUDED.expires_at
                WHERE retrade_leases.expires_at < NOW() RETURNING owner""",
                (session_id, owner, utcnow() + timedelta(seconds=ttl)),
            )
            acquired = await cursor.fetchone()
        if not acquired:
            raise Conflict("该会话正在处理中，请等待当前请求结束")
        try:
            yield
        finally:
            async with self._connection() as conn:
                await conn.execute("DELETE FROM retrade_leases WHERE id=%s AND owner=%s", (session_id, owner))


def create_postgres_repository(settings):
    """创建 PostgreSQL 业务仓库。"""
    return PostgresRepository(settings)
