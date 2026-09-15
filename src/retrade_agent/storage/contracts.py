"""Storage ports. PostgreSQL adapters must implement these methods, not Graph internals."""
from typing import Any, Protocol
from contextlib import AbstractAsyncContextManager


class StoragePort(Protocol):
    """业务仓库协议，声明应用层依赖的持久化能力。"""

    async def setup(self, seed_orders: list[dict]) -> None:
        """初始化仓库结构并写入种子订单。"""
        ...

    def lease(self, session_id: str, ttl: int = 240) -> AbstractAsyncContextManager:
        """为会话获取短期互斥租约，避免并发执行同一会话。"""
        ...

    async def create_session(self, session_id: str, customer_id: str) -> dict:
        """创建当前客户的新聊天会话。"""
        ...

    async def get_session(self, session_id: str) -> dict:
        """读取会话记录。"""
        ...

    async def list_sessions(self, customer_id: str) -> list[dict]:
        """列出指定客户的会话记录。"""
        ...

    async def update_session(self, session_id: str, **fields: Any) -> None:
        """更新会话字段。"""
        ...

    async def add_message(self, session_id: str, message_id: str, role: str, content: str) -> None:
        """写入一条会话消息。"""
        ...

    async def messages(self, session_id: str, limit: int = 100) -> list[dict]:
        """按时间顺序读取会话消息。"""
        ...

    async def begin_run(self, request_id: str, session_id: str, fingerprint: str) -> dict:
        """登记或复用一次幂等请求运行记录。"""
        ...

    async def finish_run(self, request_id: str, response: dict, status: str = "done") -> None:
        """保存运行最终响应和状态。"""
        ...

    async def get_run(self, request_id: str) -> dict | None:
        """读取指定请求的运行记录。"""
        ...

    async def create_ticket(self, ticket: dict) -> dict:
        """保存新建人工工单。"""
        ...

    async def get_ticket(self, ticket_id: str) -> dict:
        """读取人工工单。"""
        ...

    async def list_tickets(self, status: str | None = None) -> list[dict]:
        """按状态列出人工工单。"""
        ...

    async def save_ticket(self, ticket_id: str, updates: dict, expected_version: int | None = None) -> dict:
        """更新人工工单并进行可选版本校验。"""
        ...

    async def save_case(self, case: dict) -> dict:
        """保存售后 case 的最新状态。"""
        ...

    async def get_case(self, case_id: str) -> dict:
        """读取售后 case。"""
        ...

    async def operation(self, key: str, fingerprint: str, result: dict) -> dict:
        """用幂等键保存或读取业务操作结果。"""
        ...

    async def get_orders(self) -> list[dict]:
        """读取所有模拟订单。"""
        ...

    async def knowledge(self) -> list[dict]:
        """读取所有知识文档记录。"""
        ...

    async def put_document(self, document: dict) -> None:
        """保存知识文档记录。"""
        ...

    async def delete_document(self, document_id: str) -> None:
        """删除知识文档记录。"""
        ...

    async def append_trace(self, request_id: str, session_id: str, event: dict) -> None:
        """追加一次请求追踪事件。"""
        ...

    async def traces(self, request_id: str, limit: int = 300) -> list[dict]:
        """查询指定 request_id 的执行追踪事件。"""
        ...

    async def stats(self) -> dict:
        """统计仓库中的主要业务记录数量。"""
        ...


class CachePort(Protocol):
    """缓存协议，声明缓存、限流和资源释放能力。"""

    async def get(self, key: str) -> dict | None:
        """读取指定键的缓存或仓库记录。"""
        ...

    async def put(self, key: str, value: dict, ttl: int) -> None:
        """写入指定键的缓存或仓库记录。"""
        ...

    async def allow(self, key: str, limit: int, window: int = 60) -> bool:
        """按时间窗口执行限流判断。"""
        ...

    async def close(self) -> None:
        """释放客户端或缓存持有的资源。"""
        ...
