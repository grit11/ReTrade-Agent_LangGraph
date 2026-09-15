import json
import time
from langchain.tools import tool, ToolRuntime
from retrade_agent.models import AgentContext
from retrade_agent.graph.events import emit

def build_knowledge_tool(service):
    @tool(response_format='content_and_artifact')
    async def search_knowledge(query:str,runtime:ToolRuntime[AgentContext])->tuple[str,dict]:
        """检索平台公开知识、帮助中心、退货规则和服务费。只返回资料，无法提供私人订单信息。
        平台事实必须使用此工具核实；query 应是结合上文的独立完整问题。
        """
        start=time.perf_counter();emit('tool',tool='search_knowledge',phase='start')
        try:
            result=await service.search(query)
            payload={'ok':True,'contexts':result.contexts,'sources':result.sources,'evidence_found':result.evidence_found}
            artifact={'kind':'knowledge','tool':'search_knowledge','ok':True,
                      'sources':result.sources,'retrieval_detail':result.detail,'evidence_found':result.evidence_found}
        except Exception as exc:
            payload={'ok':False,'error':'知识检索暂不可用，不得编造平台规则'}
            artifact={'kind':'knowledge','tool':'search_knowledge','ok':False,'error_type':type(exc).__name__}
        emit('tool',tool='search_knowledge',phase='end',ok=artifact['ok'],ms=round((time.perf_counter()-start)*1000,1))
        return json.dumps(payload,ensure_ascii=False),artifact
    return search_knowledge
