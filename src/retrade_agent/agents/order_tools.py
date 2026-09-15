import json
import time
from langchain.tools import tool, ToolRuntime
from retrade_agent.models import Actor, AgentContext
from retrade_agent.errors import AppError
from retrade_agent.graph.events import emit

def build_order_tools(service):
    async def execute(name,runtime,oid=None):
        actor=Actor(runtime.context.customer_id);start=time.perf_counter()
        emit('tool',tool=name,phase='start')
        try:
            if name=='list_orders':data=await service.list_orders(actor)
            elif name=='get_logistics':data=await service.get_logistics(actor,oid)
            elif name=='get_payment_status':data=await service.get_payment(actor,oid)
            else:data=await service.get_order(actor,oid)
            payload={'ok':True,'data':data,'simulated':True}
            artifact={'kind':'order','tool':name,'ok':True,'order_id':oid,'simulated':True}
        except AppError as exc:
            payload={'ok':False,'error':exc.message,'code':exc.code}
            artifact={'kind':'order','tool':name,'ok':False,'error_code':exc.code}
        except Exception:
            payload={'ok':False,'error':'订单服务暂不可用，不得推测状态'}
            artifact={'kind':'order','tool':name,'ok':False,'error_code':'UPSTREAM_UNAVAILABLE'}
        emit('tool',tool=name,phase='end',ok=artifact['ok'],ms=round((time.perf_counter()-start)*1000,1))
        return json.dumps(payload,ensure_ascii=False),artifact
    @tool(response_format='content_and_artifact')
    async def list_orders(runtime:ToolRuntime[AgentContext])->tuple[str,dict]:
        """列出当前已认证用户的订单。没有明确订单号时使用；身份由服务端注入。"""
        return await execute('list_orders',runtime)
    @tool(response_format='content_and_artifact')
    async def get_order(order_id:str,runtime:ToolRuntime[AgentContext])->tuple[str,dict]:
        """查询当前用户的指定订单详情和状态。order_id 必须来自用户或已有订单上下文。"""
        return await execute('get_order',runtime,order_id)
    @tool(response_format='content_and_artifact')
    async def get_logistics(order_id:str,runtime:ToolRuntime[AgentContext])->tuple[str,dict]:
        """查询指定订单的物流轨迹，不推测平台没有提供的送达时间。"""
        return await execute('get_logistics',runtime,order_id)
    @tool(response_format='content_and_artifact')
    async def get_payment_status(order_id:str,runtime:ToolRuntime[AgentContext])->tuple[str,dict]:
        """查询指定订单的支付状态和支付金额，只允许读取当前用户订单。"""
        return await execute('get_payment_status',runtime,order_id)
    return [list_orders,get_order,get_logistics,get_payment_status]
