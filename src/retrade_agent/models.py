"""公共数据合同模块，不依赖 FastAPI、LangGraph 或存储实现。"""
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Domain(StrEnum):
    """客服系统支持的业务域枚举。"""

    CUSTOMER = "customer"
    ORDER = "order"
    AFTER_SALES = "after_sales"
    HUMAN = "human"


@dataclass(frozen=True)
class Actor:
    """当前请求访问者身份，包含客户编号和角色。"""

    customer_id: str
    role: Literal["customer", "staff"] = "customer"


@dataclass(frozen=True)
class AgentContext:
    """Agent 工具运行上下文，携带客户、会话、请求和当前订单信息。"""

    customer_id: str
    session_id: str
    request_id: str
    current_order_id: str | None = None


class TriageResult(BaseModel):
    """意图分流结果，描述目标业务域、原因和模型自评置信度。"""

    domain: Literal["customer", "order", "after_sales", "human"]
    reason: str = Field(default="", max_length=300)
    # A self-reported score is NOT a calibrated probability and never authorizes actions.
    confidence: float = Field(default=0.0, ge=0, le=1)


class AfterSalesExtraction(BaseModel):
    """售后信息抽取结果，只保存用户明确提供的订单与申请字段。"""

    order_id: str | None = Field(default=None, description="Only an explicit order id, otherwise null")
    issue_type: Literal["refund", "return", "damaged", "not_as_described"] | None = None
    reason: str | None = Field(default=None, max_length=1000)
    unused: bool | None = None
    cancel: bool = False
    other_domain: Literal["customer", "order"] | None = None


class Order(BaseModel):
    """模拟订单数据模型。"""

    model_config = ConfigDict(extra="forbid")
    order_id: str
    customer_id: str
    product: str
    amount_cents: int = Field(ge=0)
    status: str
    payment_status: str
    logistics: list[dict] = Field(default_factory=list)
    delivered_at: str | None = None
    special_category: bool = False
    simulated: bool = True


class PolicyDecision(BaseModel):
    """售后规则评估结果，描述是否可办、风险等级和人工审核要求。"""

    eligible: bool
    risk: Literal["low", "medium", "high"]
    reason: str
    policy_version: str = "mock-policy-v1"
    requires_manual: bool = False


class ChatResult(BaseModel):
    """聊天最终响应模型，供 JSON 和 SSE API 统一返回。"""

    reply: str
    session_id: str
    request_id: str
    domain: str = "customer"
    active_domain: str = "customer"
    intent: str = "chat"
    sources: list[str] = Field(default_factory=list)
    used_tools: list[str] = Field(default_factory=list)
    status: str = "responded"
    waiting_human: bool = False
    ticket_id: str | None = None
    case: dict | None = None
    retrieval_detail: dict = Field(default_factory=dict)
    token_usage: dict = Field(default_factory=dict)
    total_ms: float = 0
    cache_hit: bool = False
    simulated: bool = False
    engine: str = "langgraph"
