"""API 请求模型模块，集中定义外部入参的 Pydantic 校验结构。"""
from uuid import UUID, uuid4
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """严格请求模型基类，禁止 API 入参携带未声明字段。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SessionCreate(StrictModel):
    """创建会话请求模型。"""

    title: str | None = Field(default=None, max_length=80)


class ChatRequest(StrictModel):
    """聊天请求模型，包含会话、消息和幂等请求编号。"""

    session_id: UUID
    request_id: UUID = Field(default_factory=uuid4)
    message: str = Field(min_length=1, max_length=6000)


class DemoLogin(StrictModel):
    """演示登录请求模型。"""

    user: Literal["demo-customer", "demo-other"] = "demo-customer"


class TicketClaim(StrictModel):
    """工单认领请求模型。"""

    expected_version: int = Field(ge=1)


class HumanResume(StrictModel):
    """人工决策恢复请求模型。"""

    ticket_id: str = Field(min_length=1, max_length=80)
    decision: Literal["approve", "reject", "resolve"]
    message: str = Field(min_length=1, max_length=3000)
    expected_version: int = Field(ge=1)
    request_id: UUID = Field(default_factory=uuid4)


class TicketMessage(StrictModel):
    """工单留言请求模型。"""

    message: str = Field(min_length=1, max_length=3000)


class KnowledgeQuery(StrictModel):
    """知识检索请求模型。"""

    query: str = Field(min_length=1, max_length=2000)
