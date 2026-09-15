from uuid import UUID,uuid4
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class SessionCreate(StrictModel):
    title:str|None=Field(default=None,max_length=80)
class ChatRequest(StrictModel):
    session_id:UUID
    request_id:UUID=Field(default_factory=uuid4)
    message:str=Field(min_length=1,max_length=6000)
class DemoLogin(StrictModel):
    user:Literal['demo-customer','demo-other']='demo-customer'
class TicketClaim(StrictModel):
    expected_version:int=Field(ge=1)
class HumanResume(StrictModel):
    ticket_id:str=Field(min_length=1,max_length=80)
    decision:Literal['approve','reject','resolve']
    message:str=Field(min_length=1,max_length=3000)
    expected_version:int=Field(ge=1)
    request_id:UUID=Field(default_factory=uuid4)
class TicketMessage(StrictModel):
    message:str=Field(min_length=1,max_length=3000)
class KnowledgeQuery(StrictModel):
    query:str=Field(min_length=1,max_length=2000)
