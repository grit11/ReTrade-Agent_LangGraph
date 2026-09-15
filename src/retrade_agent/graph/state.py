"""Parent checkpoints contain JSON DTOs, not clients, keys or child-agent scratchpads.
Child create_agent graphs use their standard add_messages reducer independently.
"""
from typing_extensions import TypedDict
class CustomerServiceState(TypedDict,total=False):
    session_id:str
    request_id:str
    customer_id:str
    messages:list[dict]
    user_message:str
    active_domain:str|None
    prior_domain:str|None
    current_order_id:str|None
    triage_reason:str
    triage_confidence:float
    handoff:dict|None
    handoff_count:int
    need_human:bool
    handoff_reason:str
    human_ticket_id:str|None
    sources:list[str]
    used_tools:list[str]
    retrieval_detail:dict
    token_usage:dict
    after_sales_case:dict|None
    final_answer:str
    status:str
    result_domain:str
    intent:str
    error:str|None
    cache_hit:bool
