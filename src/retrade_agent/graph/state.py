"""父图检查点只保存 JSON DTO，不包含客户端、密钥或子 Agent 临时状态。

create_agent 子图独立使用其标准 add_messages reducer。
"""
from typing_extensions import TypedDict


class CustomerServiceState(TypedDict, total=False):
    """客服父图状态，贯穿会话上下文、分流结果、回复和人工转接信息。"""

    session_id: str
    request_id: str
    customer_id: str
    messages: list[dict]
    user_message: str
    active_domain: str | None
    prior_domain: str | None
    current_order_id: str | None
    triage_reason: str
    triage_confidence: float
    handoff: dict | None
    handoff_count: int
    need_human: bool
    handoff_reason: str
    human_ticket_id: str | None
    sources: list[str]
    used_tools: list[str]
    retrieval_detail: dict
    token_usage: dict
    after_sales_case: dict | None
    final_answer: str
    status: str
    result_domain: str
    intent: str
    error: str | None
    cache_hit: bool
